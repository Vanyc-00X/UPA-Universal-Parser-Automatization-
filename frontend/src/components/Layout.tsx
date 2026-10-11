import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { api, queryKeys } from '../api/client'
import { OnboardingWizard, isOnboardingDone } from './OnboardingWizard'
import { applyTheme, getStoredTheme, toggleTheme, type ThemeMode } from '../utils/theme'

interface NavItem {
  to: string
  label: string
  stage?: string
}

const NAV: NavItem[] = [
  { to: '/', label: 'Обзор' },
  { to: '/sites', label: 'Сайты', stage: '1' },
  { to: '/element-map', label: 'Карта элементов', stage: '2' },
  { to: '/scenarios', label: 'Сценарии', stage: '3' },
  { to: '/templates', label: 'Шаблоны', stage: '8' },
  { to: '/workflow', label: 'Воркфлоу', stage: '7' },
  { to: '/runs', label: 'Запуски', stage: '6' },
  { to: '/monitor', label: 'Мониторинг' },
  { to: '/help', label: 'Справка' },
  { to: '/roadmap', label: 'План работ' },
]

/** Каркас интерфейса: боковое меню, шапка с индикатором состояния, контент. */
export function Layout() {
  const [theme, setTheme] = useState<ThemeMode>(() => getStoredTheme())
  const [showOnboarding, setShowOnboarding] = useState(() => !isOnboardingDone())

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: api.health,
    refetchInterval: 15_000,
  })

  const status = health.isError ? 'down' : (health.data?.status ?? 'unknown')

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">UPA</span>
          <span className="brand__sub">Universal Parser Automatization</span>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav__item${isActive ? ' nav__item--active' : ''}`}
            >
              <span>{item.label}</span>
              {item.stage ? <span className="nav__stage">эт. {item.stage}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__foot">
          <button
            className="btn btn--tiny"
            type="button"
            onClick={() => setTheme((current) => toggleTheme(current))}
          >
            Тема: {theme === 'dark' ? 'тёмная' : 'светлая'}
          </button>
          <button
            className="btn btn--tiny"
            type="button"
            onClick={() => setShowOnboarding(true)}
            style={{ marginTop: 8 }}
          >
            Онбординг
          </button>
          <a href="/docs" target="_blank" rel="noreferrer">
            Документация API →
          </a>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar__title">
            {health.data ? `${health.data.app} · ${health.data.env}` : 'UPA'}
          </div>
          <div className={`badge badge--${status}`} title={health.error?.message ?? ''}>
            <span className="badge__dot" />
            {status === 'ok' ? 'Система работает' : null}
            {status === 'degraded' ? 'Работает частично' : null}
            {status === 'down' ? 'Бэкенд недоступен' : null}
            {status === 'unknown' ? 'Проверка…' : null}
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>

      {showOnboarding ? <OnboardingWizard onClose={() => setShowOnboarding(false)} /> : null}
    </div>
  )
}
