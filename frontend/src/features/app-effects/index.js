// features/app-effects 配線 entry (= W2 Phase F-5、 2026-06-29)。
//
// AppEffects.jsx は不可視 sentinel (= return null) で、 旧 AppShell.jsx に詰まっていた
// app-wide effect 群 (= viewModes 永続化 / visibility 連動 desktopOpen close / deep-link /
// notification clear / SW active-session post / Web Push 購読) を 1 経路で集約する。
// Layout.jsx が <AppEffects /> を 1 行配置するだけで全副作用が起動する。
//
// Topbar.jsx と同様、 常時 mount component で overlay でないため Component lazy spec は不要
// (= main bundle 同梱で OK、 features/__contracts__/no-lazy-component-static-import.test.js の
// Component spec 件数は不変)。 register は他 feature と並ぶための単なる名前付けで、
// dispatch action は持たない。

import { register as registerFeature } from '../../registry/featureRegistry.js'

const noopDispatch = () => null
registerFeature('app-effects', {
  dispatch: noopDispatch,
})
