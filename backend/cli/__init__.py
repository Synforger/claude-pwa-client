"""backend の CLI ユーティリティ群 (= 開発者が手動で 1 度だけ実行する小物)。

crosscut-F-21: 旧 `backend/gen_vapid.py` 等の「main 関数 + argparse」 系を `backend/cli/`
配下に集約。 ルーティング / state を持つ実行時 module (= routes / jsonl / terminal) と
分離して、 import 経路 (= 起動時の重い import を踏まない) と意図 (= ops 補助) を明確にする。
"""
