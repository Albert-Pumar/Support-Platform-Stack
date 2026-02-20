import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// Global font import
const link = document.createElement('link')
link.rel = 'stylesheet'
link.href = 'https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Mono:wght@300;400;500&family=Lora:ital,wght@0,400;0,500;1,400&display=swap'
document.head.appendChild(link)

// Global reset
const style = document.createElement('style')
style.textContent = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body, #root { height: 100%; }
  body { background: #f4f3ff; color: #1a1340; -webkit-font-smoothing: antialiased; }
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-thumb { background: #ddd8f8; border-radius: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  * { scrollbar-width: thin; scrollbar-color: #ddd8f8 transparent; }
`
document.head.appendChild(style)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
