#!/usr/bin/env node
// tests/negative/*.yaml を 1 つずつ meta-schema validate にかけ、
// 全 file が FAIL することを確認する (= 1 件でも PASS したら逆に test 失敗)。
// 使い方: node codegen/validate-negative.mjs
// exit code: 0 = 全 file 期待通り FAIL / 1 = どれかが PASS してしまった (= negative test broken)

import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import yaml from 'js-yaml'

const __dirname = dirname(fileURLToPath(import.meta.url))
const negDir = join(__dirname, '..', 'tests', 'negative')
const schemaPath = join(__dirname, '..', 'schema', '_meta.json')

const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats.default(ajv)
const validate = ajv.compile(JSON.parse(readFileSync(schemaPath, 'utf8')))

const files = readdirSync(negDir).filter(f => f.endsWith('.yaml') || f.endsWith('.yml'))
if (files.length === 0) {
  console.log('(no negative yaml fixtures)')
  process.exit(0)
}

let unexpectedPass = 0
for (const file of files) {
  let doc
  try {
    doc = yaml.load(readFileSync(join(negDir, file), 'utf8'))
  } catch (e) {
    console.log(`OK   ${file} (yaml parse error counts as expected failure: ${e.message.split('\n')[0]})`)
    continue
  }
  const ok = validate(doc)
  if (ok) {
    console.error(`FAIL ${file}: expected validation to fail, but it PASSED (= negative fixture is no longer negative)`)
    unexpectedPass += 1
  } else {
    console.log(`OK   ${file} (failed as expected)`)
  }
}

if (unexpectedPass > 0) {
  console.error(`\n${unexpectedPass}/${files.length} negative fixture(s) unexpectedly passed`)
  process.exit(1)
}
console.log(`\nall ${files.length} negative fixture(s) failed as expected`)
