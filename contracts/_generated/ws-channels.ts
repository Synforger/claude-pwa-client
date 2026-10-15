/** GENERATED FILE — do not edit by hand.
 * Source: contracts/schema/ws-channels.yaml
 */

export const WS_CHANNELS_SCHEMA_VERSION = "1.0" as const

export interface PtyClientToServer1V0 {
  type: "resize"
  rows: number
  cols: number
}

export interface PtyClientToServer1V1 {
  type: "ping"
  /** client epoch ms (= pong で echo back) */
  ts: number
}

export type PtyClientToServer1 = PtyClientToServer1V0 | PtyClientToServer1V1

export interface PtyServerToClient1V0 {
  type: "exit" | "error"
  message?: string
}

export interface PtyServerToClient1V1 {
  type: "pong"
  /** client から受信した ts を echo */
  ts: number
}

export type PtyServerToClient1 = PtyServerToClient1V0 | PtyServerToClient1V1

export interface ViewsClientToServer0V0 {
  /** null = 全タブ非表示 */
  sid?: string | null
}

export interface ViewsClientToServer0V1 {
  type: "stop"
  sid: string
}

export type ViewsClientToServer0 = ViewsClientToServer0V0 | ViewsClientToServer0V1

export interface DeviceClientToServer0V0 {
  type: "hello"
  device?: string
  app?: string
  catalog: unknown[]
}

export interface DeviceClientToServer0V1 {
  type: "result"
  id: string
  ok: boolean
  result?: unknown
  error?: string
  /** [{name, mime, data (= base64)}] */
  files?: unknown[]
}

export type DeviceClientToServer0 = DeviceClientToServer0V0 | DeviceClientToServer0V1

export interface DeviceServerToClient0 {
  type: "call"
  id: string
  op: string
  args: Record<string, unknown>
}
