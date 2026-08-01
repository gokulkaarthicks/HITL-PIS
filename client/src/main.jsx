import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import DocsPage from './components/DocsPage.jsx'
import './index.css'

const normalizedPath = window.location.pathname.replace(/\/+$/, '') || '/'
const RootPage = normalizedPath === '/docs' ? DocsPage : App

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RootPage />
  </React.StrictMode>,
)
