// transport 実装の選択点 (= 現在は unified 1 本、 2026-07-27 legacy 退役)。
//
// 2026-07-14 の電力効率工事で unified (= 1 本多重化接続) を導入し、 旧 4-5 本構成は
// `cpc_transport=legacy` の rollback 経路として温存していた。 2026-07-27 の退役 audit で
// legacy 実利用が「古い bundle を開いたままのタブの居座り」 だけと確認できたため、
// flag ごと物理削除した (= 切替 UI は元々無く、 復旧経路としての実用性が無かった)。
//
// consumer は本 module からだけ import する (= unified.ts を直接 import する経路を
// 増やすと、 将来の transport 差し替えがまた二重管理になる)。

import {
  unifiedJsonl,
  unifiedOverviewSse,
  unifiedStatusSse,
  unifiedSubagentsSse,
  unifiedTransport,
  unifiedViews,
} from './unified.ts'

/** chat jsonl 経路 (= SseTransport 互換 + setSubscribedSids)。 */
export const chatTransport = unifiedJsonl

export const statusSse = unifiedStatusSse
export const overviewSse = unifiedOverviewSse
export const subagentsStreamSse = unifiedSubagentsSse
export const viewsChannel = unifiedViews

/** lifecycle.ts の fg/bg bump 用 (= 1 接続 bump で全 channel 蘇生)。 */
export { unifiedTransport }
