#!/usr/bin/env node
// yaml schema → TypeScript types 生成。
//
// 設計判断:
//   - openapi-typescript は OpenAPI 入力前提で自前 yaml に不適合、 自前 codegen で書く (= ADR-011 自前ハイブリッド)。
//   - 出力先: --out で指定、 デフォルトは contracts/_generated/。 frontend/src/ への配置切替は Phase 5。
//   - additionalProperties: false → exact type (= TS default)、 true → & Record<string, unknown>。
//
// 使い方:
//   node codegen/gen-types.mjs                             # contracts/_generated/types.ts
//   node codegen/gen-types.mjs --out ../frontend/src        # frontend に直接書き出し (Phase 5)
//   node codegen/gen-types.mjs --check                     # 既存出力との diff のみ、 書き換えない (= CI gate)

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'

const __dirname = dirname(fileURLToPath(import.meta.url))
const schemaDir = resolve(__dirname, '..', 'schema')
const defaultOut = resolve(__dirname, '..', '_generated')

function pascal(name) {
  return name.split(/[_\-]/).filter(Boolean).map(p => p[0].toUpperCase() + p.slice(1)).join('')
}

function tsType(schema, depth = 0) {
  if (!schema || typeof schema !== 'object') return 'unknown'
  if ('const' in schema) {
    const v = schema.const
    return typeof v === 'string' ? `"${v}"` : JSON.stringify(v)
  }
  if (schema.enum) {
    return schema.enum.map(v => typeof v === 'string' ? `"${v}"` : JSON.stringify(v)).join(' | ')
  }
  if (schema.oneOf || schema.anyOf) {
    const variants = schema.oneOf || schema.anyOf
    return variants.map(v => tsType(v, depth + 1)).join(' | ')
  }
  switch (schema.type) {
    case 'string':  return 'string'
    case 'integer':
    case 'number':  return 'number'
    case 'boolean': return 'boolean'
    case 'null':    return 'null'
    case 'array': {
      const item = tsType(schema.items || {}, depth + 1)
      // 単純型でなければ括弧で囲む
      const needsParen = / |&/.test(item)
      return needsParen ? `(${item})[]` : `${item}[]`
    }
    case 'object': {
      const props = schema.properties || {}
      const required = new Set(schema.required || [])
      const additional = schema.additionalProperties
      const propEntries = Object.entries(props)
      // properties 空 + additional schema → Record<string, T> 単体で返す (= TS interface に & 合成不可の回避)
      if (propEntries.length === 0 && additional && typeof additional === 'object' && additional.type) {
        return `Record<string, ${tsType(additional, depth + 1)}>`
      }
      if (propEntries.length === 0 && additional !== false) {
        return 'Record<string, unknown>'
      }
      const lines = []
      const indent = '  '.repeat(depth + 1)
      for (const [name, sub] of propEntries) {
        const t = tsType(sub, depth + 1)
        const nullable = sub.nullable ? ' | null' : ''
        const opt = required.has(name) && !sub.nullable ? '' : '?'
        const desc = sub.description ? `${indent}/** ${sub.description} */\n` : ''
        lines.push(`${desc}${indent}${name}${opt}: ${t}${nullable}`)
      }
      const indentClose = '  '.repeat(depth)
      let body = `{\n${lines.join('\n')}\n${indentClose}}`
      if (additional === true) body += ' & Record<string, unknown>'
      if (additional && typeof additional === 'object' && additional.type) {
        body += ` & Record<string, ${tsType(additional, depth + 1)}>`
      }
      return body
    }
    default: return 'unknown'
  }
}

function emitInterface(name, schema, description = '') {
  const props = { ...(schema.properties || {}) }
  const required = [...(schema.required || [])]
  const additional = schema.additionalProperties
  const propEntries = Object.entries(props)
  const lines = []
  if (description) lines.push(`/** ${description} */`)
  // properties 空 → interface body が `{}` か Record になり TS が嫌がるので type alias に切替
  if (propEntries.length === 0) {
    if (additional && typeof additional === 'object' && additional.type) {
      lines.push(`export type ${name} = Record<string, ${tsType(additional, 1)}>`)
    } else if (additional === false) {
      // exact empty (= 何も持たない object)
      lines.push(`export type ${name} = Record<string, never>`)
    } else {
      lines.push(`export type ${name} = Record<string, unknown>`)
    }
    return lines.join('\n') + '\n'
  }
  const body = tsType({ type: 'object', properties: props, required, additionalProperties: additional })
  lines.push(`export interface ${name} ${body}`)
  return lines.join('\n') + '\n'
}

function genEvents(doc) {
  const out = []
  out.push(`/** GENERATED FILE — do not edit by hand.\n * Source: contracts/schema/sse-events.yaml\n * Regenerate: cd contracts && npm run codegen:types\n */`)
  out.push(`\nexport const SSE_EVENTS_SCHEMA_VERSION = "${doc.schema_version}" as const\n`)
  const names = []
  for (const [evName, ev] of Object.entries(doc.events || {})) {
    const className = pascal(evName) + 'Event'
    names.push([evName, className])
    // type field を inline で含める (= frontend event.type 分岐用)
    const schema = {
      type: 'object',
      properties: { type: { const: evName }, ...(ev.properties || {}) },
      required: ['type', ...(ev.required || [])],
      additionalProperties: ev.additionalProperties,
    }
    out.push(emitInterface(className, schema, ev.description))
  }
  if (names.length > 0) {
    out.push(`\nexport type AnySseEvent = ${names.map(([, c]) => c).join(' | ')}\n`)
    out.push(`\nexport const SSE_EVENT_TYPES = [${names.map(([n]) => `"${n}"`).join(', ')}] as const\n`)
    out.push(`export type SseEventType = typeof SSE_EVENT_TYPES[number]\n`)
  }
  return out.join('\n')
}

function genWsChannels(doc) {
  const out = []
  out.push(`/** GENERATED FILE — do not edit by hand.\n * Source: contracts/schema/ws-channels.yaml\n */`)
  out.push(`\nexport const WS_CHANNELS_SCHEMA_VERSION = "${doc.schema_version}" as const\n`)
  for (const [chName, ch] of Object.entries(doc.channels || {})) {
    const prefix = pascal(chName)
    for (const dir of ['client_to_server', 'server_to_client']) {
      const frames = ch[dir] || []
      frames.forEach((frame, idx) => {
        if (!frame.schema) return
        const baseName = `${prefix}${pascal(dir)}${idx}`
        if (frame.schema.oneOf) {
          const variantNames = []
          frame.schema.oneOf.forEach((v, vi) => {
            const cn = `${baseName}V${vi}`
            variantNames.push(cn)
            out.push(emitInterface(cn, v))
          })
          out.push(`export type ${baseName} = ${variantNames.join(' | ')}\n`)
        } else if (frame.schema.type === 'object') {
          out.push(emitInterface(baseName, frame.schema))
        }
      })
    }
  }
  return out.join('\n')
}

function genHttpEndpoints(doc) {
  const out = []
  out.push(`/** GENERATED FILE — do not edit by hand.\n * Source: contracts/schema/http-endpoints.yaml\n */`)
  out.push(`\nexport const HTTP_ENDPOINTS_SCHEMA_VERSION = "${doc.schema_version}" as const\n`)
  for (const ep of doc.endpoints || []) {
    const method = ep.method.toLowerCase()
    const pathWords = ep.path.match(/[a-zA-Z0-9]+/g) || []
    const epName = pascal(pathWords.join('_'))
    const prefix = pascal(method) + epName
    if (ep.request_body && ep.request_body.type === 'object') {
      out.push(emitInterface(`${prefix}Request`, ep.request_body, `${ep.method} ${ep.path} request body`))
    }
    if (ep.response && ep.response.type === 'object') {
      out.push(emitInterface(`${prefix}Response`, ep.response, `${ep.method} ${ep.path} response`))
    } else if (ep.response && ep.response.type === 'array' && ep.response.items?.type === 'object') {
      out.push(emitInterface(`${prefix}ResponseItem`, ep.response.items, `${ep.method} ${ep.path} response[i]`))
      out.push(`export type ${prefix}Response = ${prefix}ResponseItem[]\n`)
    }
  }
  return out.join('\n')
}

const generators = {
  events: { yamlFile: 'sse-events.yaml', tsFile: 'sse-events.ts', fn: genEvents },
  ws_channels: { yamlFile: 'ws-channels.yaml', tsFile: 'ws-channels.ts', fn: genWsChannels },
  http_endpoints: { yamlFile: 'http-endpoints.yaml', tsFile: 'http-endpoints.ts', fn: genHttpEndpoints },
}

function parseArgs() {
  const args = { out: defaultOut, only: null, check: false, single: false }
  for (let i = 2; i < process.argv.length; i++) {
    const a = process.argv[i]
    if (a === '--out') args.out = resolve(process.argv[++i])
    else if (a === '--only') { args.only = args.only || []; args.only.push(process.argv[++i]) }
    else if (a === '--check') args.check = true
    else if (a === '--single-file') args.single = true  // 全 yaml を 1 file (= types.ts) に束ねる
  }
  return args
}

function main() {
  const args = parseArgs()
  const targets = args.only || Object.keys(generators)
  if (!existsSync(args.out)) mkdirSync(args.out, { recursive: true })

  const generated = {}
  for (const key of targets) {
    const { yamlFile, tsFile, fn } = generators[key]
    const src = join(schemaDir, yamlFile)
    if (!existsSync(src)) { console.error(`SKIP ${key}: ${src} not found`); continue }
    const doc = yaml.load(readFileSync(src, 'utf8'))
    generated[key] = { tsFile, content: fn(doc) }
  }

  if (args.single) {
    const merged = '// GENERATED FILE — do not edit by hand. Single-file bundle of all contracts.\n\n' +
      Object.values(generated).map(g => g.content).join('\n\n')
    const outPath = join(args.out, 'types.ts')
    if (args.check) {
      const existing = existsSync(outPath) ? readFileSync(outPath, 'utf8') : ''
      if (existing !== merged) { console.error(`DIFF ${outPath} differs`); process.exit(1) }
      console.log(`OK   ${outPath} matches`)
    } else {
      writeFileSync(outPath, merged)
      console.log(`WROTE ${outPath}`)
    }
    return
  }

  let differ = 0
  for (const [key, { tsFile, content }] of Object.entries(generated)) {
    const outPath = join(args.out, tsFile)
    if (args.check) {
      const existing = existsSync(outPath) ? readFileSync(outPath, 'utf8') : ''
      if (existing !== content) { console.error(`DIFF ${outPath} differs`); differ++ } else console.log(`OK   ${outPath} matches`)
    } else {
      writeFileSync(outPath, content)
      console.log(`WROTE ${outPath}`)
    }
  }
  if (args.check && differ > 0) process.exit(1)
}

main()
