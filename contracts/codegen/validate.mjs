#!/usr/bin/env node
// schema/*.yaml を _meta.json (= JSON Schema 2020-12) で validate する自前 runner。
// ajv-cli (= old glob / inflight 由来の vulnerabilities) を避けるため ajv API 直叩き。
// 使い方: node codegen/validate.mjs              # 全 yaml validate
//          node codegen/validate.mjs --strict     # additionalProperties: false 厳格化
// exit code: 0 = pass / 1 = fail (= yaml typo / 必須欠落 / kind 未定義)

import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname, basename } from 'node:path'
import { fileURLToPath } from 'node:url'
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import yaml from 'js-yaml'

const __dirname = dirname(fileURLToPath(import.meta.url))
const schemaDir = join(__dirname, '..', 'schema')

const strict = process.argv.includes('--strict')
const ajv = new Ajv2020({ allErrors: true, strict })
addFormats.default(ajv)

const meta = JSON.parse(readFileSync(join(schemaDir, '_meta.json'), 'utf8'))
const validate = ajv.compile(meta)

const files = readdirSync(schemaDir).filter(f => f.endsWith('.yaml') || f.endsWith('.yml'))
if (files.length === 0) {
  console.log('(no yaml files in schema/, nothing to validate)')
  process.exit(0)
}

let failed = 0
for (const file of files) {
  const path = join(schemaDir, file)
  let doc
  try {
    doc = yaml.load(readFileSync(path, 'utf8'))
  } catch (e) {
    console.error(`FAIL ${file}: yaml parse error: ${e.message}`)
    failed += 1
    continue
  }
  const ok = validate(doc)
  if (ok) {
    console.log(`PASS ${file}`)
  } else {
    console.error(`FAIL ${file}:`)
    for (const err of validate.errors ?? []) {
      console.error(`  ${err.instancePath || '/'} ${err.message} ${err.params ? JSON.stringify(err.params) : ''}`)
    }
    failed += 1
  }
}

if (failed > 0) {
  console.error(`\n${failed}/${files.length} file(s) failed validation`)
  process.exit(1)
}
console.log(`\nall ${files.length} file(s) passed`)
