"""jsonl_watcher の binding self-heal の unit test。

再 attach / backend restart の race で in-mem binding の jsonl_path が失われても、
SessionStart hook / persist 由来の確定 path (_confirmed_paths) が生きていれば
get_jsonl_for が self-heal して chat tail を復旧できることを固定する (= あるタブの chat が
急に読めなくなる事象の再発防止)。 _confirmed_paths は PWA_SID 確定のみが入るので、
同 cwd の別 claude プロセス (= デスクトップアプリ等) の混入は構造的に起きない。

注意: confirm_bind は _save_bindings() で _PERSIST_PATH に書き込む副作用を持つ。 テストでは
本番の logs/jsonl_bindings.json を壊さないよう、 autouse fixture で _PERSIST_PATH を tmp に
逃がし、 module-level の _bindings / _confirmed_paths を毎テスト clear する。
"""
import pytest

import backend.core.jsonl_watcher as jw


@pytest.fixture(autouse=True)
def isolate_watcher(tmp_path, monkeypatch):
    monkeypatch.setattr(jw, "_PERSIST_PATH", tmp_path / "bindings.json")
    jw._bindings.clear()
    jw._confirmed_paths.clear()
    yield
    jw._bindings.clear()
    jw._confirmed_paths.clear()


def test_confirm_bind_then_get(tmp_path):
    f = tmp_path / "abc.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_1", "claude_1", str(f))
    assert jw.get_jsonl_for("ses_1") == f


def test_reconfirming_the_same_binding_touches_nothing(tmp_path, monkeypatch):
    """変化の無い再確認は disk も log も触らない。

    SessionStart / UserPromptSubmit 等の hook は turn ごとに飛んでくるので、 確定済み binding
    への「同じ path をもう一度」 が呼び出しの大半を占める。 旧実装はそれでも毎回 detach 走査 +
    INFO ログ + bindings 書き出しまで走っていた (= 2026-08-03 実測 2,158 回、 うち 1 セッション
    だけで 1,055 回)。
    """
    f = tmp_path / "same.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_x", "claude_x", str(f))

    saves = []
    monkeypatch.setattr(jw, "_save_bindings", lambda: saves.append(1))
    logs = []
    monkeypatch.setattr(jw.logger, "info", lambda *a, **k: logs.append(a))

    assert jw.confirm_bind("ses_x", "claude_x", str(f)) == f
    assert saves == []
    assert logs == []

    # path が変わる (= /clear で新しい jsonl に切り替わった) 時は従来どおり反映する
    g = tmp_path / "next.jsonl"
    g.write_text("{}\n")
    assert jw.confirm_bind("ses_x", "claude_x2", str(g)) == g
    assert len(saves) == 1
    assert len(logs) == 1
    assert jw.get_jsonl_for("ses_x") == g


def test_self_heal_when_inmem_binding_lost(tmp_path):
    # 確定後に in-mem binding が null 化 (= 再 attach race を模す) しても、
    # _confirmed_paths から復元して返すこと。
    f = tmp_path / "tab.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_tab", "claude_tab", str(f))
    jw._bindings["ses_tab"].jsonl_path = None
    jw._bindings["ses_tab"].confirmed = False
    assert jw.get_jsonl_for("ses_tab") == f
    assert jw._bindings["ses_tab"].jsonl_path == f
    assert jw._bindings["ses_tab"].confirmed is True


def test_self_heal_when_binding_entry_gone(tmp_path):
    # _bindings entry ごと消えても _confirmed_paths から復元する。
    f = tmp_path / "x.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_2", "claude_2", str(f))
    jw._bindings.pop("ses_2")
    assert jw.get_jsonl_for("ses_2") == f


def test_no_heal_when_confirmed_file_missing(tmp_path):
    # 確定 path のファイルが消えていれば None (= 存在しない物を bind しない)。
    jw._confirmed_paths["ses_3"] = tmp_path / "gone.jsonl"
    assert jw.get_jsonl_for("ses_3") is None


def test_list_bindings_exposes_confirmed_flag(tmp_path):
    # hooks_router._pwa_session_for_claude_sid が confirmed の serialize を見て
    # 通知の宛先を絞っているので、 list_bindings は confirmed を必ず露出する。
    # 露出が落ちると全 hook が non_pwa_session 扱いになり通知が止まる (= 2026-05-28 実機回帰)。
    f = tmp_path / "ok.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_c", "claude_c", str(f))
    jw._bindings["ses_u"] = jw._ClaudeBinding(
        tmux_sid="ses_u", claude_pid=0, claude_cwd=str(tmp_path), start_time=0.0,
        jsonl_path=f, confirmed=False,
    )
    listed = jw.list_bindings()
    assert listed["ses_c"]["confirmed"] is True
    assert listed["ses_u"]["confirmed"] is False


def test_confirm_bind_detaches_stale_and_blocks_reheal(tmp_path):
    # 同 path を持つ別 binding を confirm_bind が剥がし、 self-heal で復帰させないこと
    # (= 1 JSONL が 2 タブに流れる cross-contamination 防止)。
    f = tmp_path / "shared.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_old", "c_old", str(f))
    jw.confirm_bind("ses_new", "c_new", str(f))
    assert jw.get_jsonl_for("ses_new") == f
    assert jw.get_jsonl_for("ses_old") is None


def test_register_pending_does_not_probabilistically_bind(tmp_path):
    # 確率窓マッチ廃止の回帰 (= 2026-05-29 cross-contamination 真因)。 spawn 直後に同 cwd へ
    # 起動時刻が近い jsonl が在っても、 register_pending は birthtime 推測で紐付けない。
    # 紐付けは hook の confirm_bind が来るまで起きず、 get_jsonl_for は None を返す。
    (tmp_path / "tempting.jsonl").write_text("{}\n")
    jw.register_pending("ses_a", 1, str(tmp_path), 1000.0)
    jw.register_pending("ses_b", 2, str(tmp_path), 1000.0)  # 同 cwd 2 セッション
    assert jw.get_jsonl_for("ses_a") is None
    assert jw.get_jsonl_for("ses_b") is None


def test_binding_is_dropped_when_its_jsonl_disappears(tmp_path):
    # 起動時 (_load_bindings) は実体の無い binding を復元しないのに、 稼働中に実体が
    # 消えた分を落とす経路が無く、 健康確認が赤いまま自己修復しなかった回帰。
    f = tmp_path / "vanishing.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_gone", "c_gone", str(f))
    assert "ses_gone" in jw.list_bindings()

    f.unlink()
    assert "ses_gone" not in jw.list_bindings()


def test_pruning_keeps_bindings_whose_jsonl_still_exists(tmp_path):
    # 掃除が生きている binding を巻き込まないこと (= 落とす条件は実体の不在だけ)。
    alive = tmp_path / "alive.jsonl"
    alive.write_text("{}\n")
    dead = tmp_path / "dead.jsonl"
    dead.write_text("{}\n")
    jw.confirm_bind("ses_alive", "c_alive", str(alive))
    jw.confirm_bind("ses_dead", "c_dead", str(dead))

    dead.unlink()
    assert jw.prune_dead_bindings() == ["ses_dead"]
    assert jw.get_jsonl_for("ses_alive") == alive


def _restart():
    """backend の再起動: メモリの状態を捨てて、 保存した file から読み直す。"""
    jw._bindings.clear()
    jw._confirmed_paths.clear()
    jw._load_bindings()


def test_a_session_bound_before_its_jsonl_is_born_survives_a_restart(tmp_path):
    """起動したばかりのタブの binding が、 backend の再起動で消えない。

    SessionStart hook は claude が JSONL を作る前に飛ぶ。 その直後の hook が binding を引く時に
    掃除が走り、 「まだ生まれていない」 を「消えた」 と読んで binding を落とし、 落とした状態を
    保存していた。 JSONL が生まれるとメモリの上では戻るが、 保存はされず、 以後の hook は
    「変化なし」 で何も書かない。 その状態で backend を再起動すると、 そのタブだけ会話の記録を
    引けなくなる (= 次に発話するまで履歴も流し直しも空。 2026-10-06 の実機: 5 タブ中 4 だけ復元)。
    """
    f = tmp_path / "fresh.jsonl"  # まだ無い
    jw.confirm_bind("ses_new", "claude_new", str(f))
    jw.list_bindings()  # 次の hook が binding を引く (= 掃除が走る)
    assert jw._bindings.get("ses_new") is not None, "生まれる前の binding を落としている"

    f.write_text("{}\n")  # claude が最初の行を書く
    assert jw.get_jsonl_for("ses_new") == f
    assert jw.confirm_bind("ses_new", "claude_new", str(f)) == f  # 以後の hook (= 変化なし)

    _restart()
    assert jw.get_jsonl_for("ses_new") == f


def test_an_unborn_binding_is_not_listed_as_existing(tmp_path):
    """生まれる前の binding は持ち続けるが、 「在る」 一覧には出さない (= 一覧に出た物は実体を持つ)。"""
    f = tmp_path / "fresh.jsonl"
    jw.confirm_bind("ses_new", "claude_new", str(f))
    assert "ses_new" not in jw.list_bindings()
    f.write_text("{}\n")
    assert jw.list_bindings()["ses_new"]["jsonl_path"] == str(f)


def test_a_healed_binding_is_saved(tmp_path):
    """メモリの上で復元した binding は、 保存した file にも戻る。

    消えた JSONL が戻った時 (= 掃除で落とした後)、 復元をメモリだけに留めると、 保存した file は
    落としたままになり、 次の再起動でそのタブを見失う。
    """
    f = tmp_path / "back.jsonl"
    f.write_text("{}\n")
    jw.confirm_bind("ses_back", "claude_back", str(f))
    f.unlink()
    assert jw.prune_dead_bindings() == ["ses_back"]
    f.write_text("{}\n")  # 戻った
    assert jw.get_jsonl_for("ses_back") == f

    _restart()
    assert jw.get_jsonl_for("ses_back") == f


def test_a_binding_whose_jsonl_never_appears_is_not_restored(tmp_path):
    """最後まで生まれなかった JSONL の binding は、 再起動で持ち越さない。"""
    f = tmp_path / "never.jsonl"
    jw.confirm_bind("ses_never", "claude_never", str(f))
    jw.list_bindings()
    _restart()
    assert jw.get_jsonl_for("ses_never") is None
    assert "ses_never" not in jw._bindings
