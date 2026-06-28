// features/topbar 配線 entry (= W2 Phase F-3、 2026-06-29)。
//
// Topbar は overlay でない常時 mount component なので registerFeature で配線 (= bookkeeping)。
// AppShell.jsx が <Topbar /> を直接 render するため、 Component lazy spec は持たない (= main bundle
// 同梱で OK、 features/__contracts__/no-lazy-component-static-import.test.js の Component spec
// 件数は不変)。 また Topbar.jsx は lazy 対象でない常時 mount component なので、 本 entry からの
// static import 禁止対象でもない (= 同 contract test の AppShell lazy target 集合に含まれない)。

import { register as registerFeature } from '../../registry/featureRegistry.js'

registerFeature('topbar', { dispatch: () => null })
