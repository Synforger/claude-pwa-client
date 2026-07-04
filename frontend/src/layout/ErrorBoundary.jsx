import { Component } from 'react'
import { tRaw } from '../i18n/t.js'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100dvh',
          gap: '16px',
          fontFamily: 'sans-serif',
          color: '#ccc',
          background: '#1a1a1a',
        }}>
          <p style={{ margin: 0, fontSize: '14px' }}>{tRaw('boundary.error')}</p>
          <pre style={{
            fontSize: '11px',
            color: '#888',
            maxWidth: '80vw',
            overflow: 'auto',
            margin: 0,
          }}>
            {this.state.error?.stack || this.state.error?.message}
          </pre>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '8px 20px',
                background: '#333',
                color: '#ccc',
                border: '1px solid #555',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              {tRaw('common.reload')}
            </button>
            <button
              onClick={() => { localStorage.clear(); window.location.reload() }}
              style={{
                padding: '8px 20px',
                background: '#2a1a1a',
                color: '#aaa',
                border: '1px solid #553333',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              {tRaw('boundary.reset')}
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
