// ToolUse / ToolResult 型 + 純粋判定。 React / DOM 非依存。

/** Anthropic tool_use block (= assistant message.content の type=tool_use)。 */
export interface ToolUse {
  id: string
  name: string
  input: Record<string, unknown>
  /** ToolResult が紐付いた後に充填される (= reconcile 経路、 domain/Message attachToolResults)。 */
  result?: { content: unknown; is_error: boolean }
}

/** Anthropic tool_result block (= user message.content の type=tool_result)。 */
export interface ToolResult {
  tool_use_id: string
  content: unknown
  is_error?: boolean
}

/** chat 表示で除外する tool 群 (= v1 components/MessageItem.jsx の filter ロジックを純粋化)。
 *  Agent / AskUserQuestion / TodoWrite は専用 bubble / overlay で別表示するため tools array から外す。 */
const EXCLUDED_FROM_INLINE_TOOLS = new Set(['Agent', 'AskUserQuestion', 'TodoWrite'])

export function isInlineTool(tool: ToolUse): boolean {
  return !EXCLUDED_FROM_INLINE_TOOLS.has(tool.name)
}

/** Bash / Read / Write / Edit 等 file-system 系の判定 (= diff view 等の分岐に使う)。 */
const FS_TOOL_NAMES = new Set(['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'NotebookEdit'])

export function isFileSystemTool(tool: ToolUse): boolean {
  return FS_TOOL_NAMES.has(tool.name)
}

/** Workflow / Task / SubAgent 系 (= 🤖 chip で SubAgent panel に飛ぶ判定)。 */
const SUBAGENT_TOOL_NAMES = new Set(['Task', 'Workflow', 'Agent'])

export function isSubagentTool(tool: ToolUse): boolean {
  return SUBAGENT_TOOL_NAMES.has(tool.name)
}
