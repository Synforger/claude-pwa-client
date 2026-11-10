/**
 * What one terminal socket does with what the backend sends it.
 *
 * The first binary frame of a connection is the pane's current screen (a snapshot that
 * clears the screen and paints every row), so the terminal is reset right before it: the
 * old screen stays visible until the new one is ready to replace it, instead of going
 * blank while the socket opens. When the backend could not take a snapshot it says so
 * with `{type:'snapshot', status:'none'}`, and the terminal asks the program in the pane
 * to repaint itself with Ctrl-L.
 *
 * Used by Terminal.jsx, one feed per socket.
 */

const CTRL_L = '\x0c'

/**
 * @param {{terminal: import('@xterm/xterm').Terminal, sendKeys: (keys: string) => void, onExit?: (ctrl: object) => void}} options
 * @returns {{handleMessage: (data: string | ArrayBuffer) => void}}
 */
export function createScreenFeed({ terminal, sendKeys, onExit }) {
  let resetPending = true

  const handleControl = (text) => {
    let ctrl
    try {
      ctrl = JSON.parse(text)
    } catch {
      return
    }
    if (ctrl.type === 'exit') {
      terminal.write(`\r\n\x1b[31m[backend reports PTY exited rc=${ctrl.returncode}]\x1b[0m\r\n`)
      onExit?.(ctrl)
    } else if (ctrl.type === 'error') {
      terminal.write(`\r\n\x1b[31m[backend error: ${ctrl.message}]\x1b[0m\r\n`)
    } else if (ctrl.type === 'snapshot' && ctrl.status === 'none') {
      sendKeys(CTRL_L)
    }
  }

  const handleMessage = (data) => {
    if (typeof data === 'string') {
      handleControl(data)
      return
    }
    if (resetPending) {
      resetPending = false
      terminal.reset()
    }
    terminal.write(new Uint8Array(data))
  }

  return { handleMessage }
}
