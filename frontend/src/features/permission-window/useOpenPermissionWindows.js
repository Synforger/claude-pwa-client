import { useEffect, useState } from 'react'
import { statusSse } from '../../transport/select.ts'
import { sidsWithWindow } from './windowSids.js'

// The ids of the tabs that have a permission window open, for the marks in the list of tabs. It follows the status
// stream (every tab in one snapshot) and starts empty: a mark left over from an earlier session could say a window is
// open when it is not.

/** @returns {Set<string>} */
export function useOpenPermissionWindows() {
  const [sids, setSids] = useState(() => new Set())
  useEffect(() => statusSse.subscribe(data => setSids(sidsWithWindow(data))), [])
  return sids
}
