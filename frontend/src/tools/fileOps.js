// 標準 file 操作系 (Bash / Read / Write / Edit / Glob / Grep)。
// Edit / Write は MessageItem 側で diff 描画するため diffInput を返す。
import { truncate } from './_shared.js'

export const Bash = {
  format(input) {
    const label = `$ ${input?.command ?? ''}`
    return { label, shortLabel: truncate(label) }
  },
}

export const Read = {
  format(input) {
    const label = `read  ${input?.file_path ?? ''}`
    return { label, shortLabel: truncate(label) }
  },
}

export const Write = {
  format(input) {
    const label = `write ${input?.file_path ?? ''}`
    const diffInput = input && typeof input === 'object'
      ? { kind: 'write', file_path: input.file_path, content: input.content ?? '' }
      : null
    return { label, shortLabel: truncate(label), diffInput }
  },
}

export const Edit = {
  format(input) {
    const all = input?.replace_all ? ' (all)' : ''
    const label = `edit  ${input?.file_path ?? ''}${all}`
    const diffInput = input && typeof input === 'object'
      ? {
          kind: 'edit',
          file_path: input.file_path,
          old_string: input.old_string ?? '',
          new_string: input.new_string ?? '',
          replace_all: !!input.replace_all,
        }
      : null
    return { label, shortLabel: truncate(label), diffInput }
  },
}

export const Glob = {
  format(input) {
    const label = `glob  ${input?.pattern ?? ''}`
    return { label, shortLabel: truncate(label) }
  },
}

export const Grep = {
  format(input) {
    const label = `grep  ${input?.pattern ?? ''}`
    return { label, shortLabel: truncate(label) }
  },
}
