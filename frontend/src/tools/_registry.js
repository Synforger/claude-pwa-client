// tool name → handler の lookup table。 utils/format.js は formatTool() からこの
// registry を引いて handler.format(input) に丸投げするだけ。
//
// 新 tool 追加手順:
//   1) 既存 family (fileOps / web / cron / task / worktree / misc / agent / todoPlan)
//      のどこかに `export const <Name> = { format(input) { ... } }` を 1 つ書く
//   2) このファイルに `import` + registry に 1 行足す
//   3) 既存の default fallback (MCP / 未知 tool) は formatTool() 側に残してあるので、
//      registry に無くても自動で `[displayName] <JSON>` 表示にはなる。 表示を作り
//      込みたい時だけ handler を書く。
import * as fileOps from './fileOps.js'
import * as web from './web.js'
import * as todoPlan from './todoPlan.js'
import * as agent from './agent.js'
import * as cron from './cron.js'
import * as worktree from './worktree.js'
import * as task from './task.js'
import * as misc from './misc.js'

const toolHandlers = {
  // file 操作
  Bash: fileOps.Bash,
  Read: fileOps.Read,
  Write: fileOps.Write,
  Edit: fileOps.Edit,
  Glob: fileOps.Glob,
  Grep: fileOps.Grep,
  // web
  WebSearch: web.WebSearch,
  WebFetch: web.WebFetch,
  // todo + plan
  TodoWrite: todoPlan.TodoWrite,
  ExitPlanMode: todoPlan.ExitPlanMode,
  EnterPlanMode: todoPlan.EnterPlanMode,
  // agent / question / monitor
  AskUserQuestion: agent.AskUserQuestion,
  Monitor: agent.Monitor,
  Agent: agent.Agent,
  Task: agent.Task,
  Workflow: agent.Workflow,
  // cron / schedule
  CronCreate: cron.CronCreate,
  CronDelete: cron.CronDelete,
  CronList: cron.CronList,
  ScheduleWakeup: cron.ScheduleWakeup,
  // worktree
  EnterWorktree: worktree.EnterWorktree,
  ExitWorktree: worktree.ExitWorktree,
  // task tracker / background
  TaskOutput: task.TaskOutput,
  TaskStop: task.TaskStop,
  TaskCreate: task.TaskCreate,
  TaskUpdate: task.TaskUpdate,
  TaskGet: task.TaskGet,
  TaskList: task.TaskList,
  // その他単発
  PushNotification: misc.PushNotification,
  NotebookEdit: misc.NotebookEdit,
  RemoteTrigger: misc.RemoteTrigger,
  Skill: misc.Skill,
  ToolSearch: misc.ToolSearch,
  ShareOnboardingGuide: misc.ShareOnboardingGuide,
}

export function getToolHandler(name) {
  return toolHandlers[name] || null
}

export default toolHandlers
