"""config.json の雛形を置く。 設定の置き場 (= `backend._common.paths.CONFIG_PATH`) に config.json が無い時だけ configs/config.example.json を写す。

`task setup` が呼ぶ。 使い方:
    python -m backend.cli.init_config
"""
import shutil

from backend._common.paths import CONFIG_PATH, REPO_ROOT


def main() -> None:
    if CONFIG_PATH.exists():
        print(f"→ {CONFIG_PATH} already present (skip)")
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "configs" / "config.example.json", CONFIG_PATH)
    print(f"→ created {CONFIG_PATH} from example. EDIT IT before next steps.")


if __name__ == "__main__":
    main()
