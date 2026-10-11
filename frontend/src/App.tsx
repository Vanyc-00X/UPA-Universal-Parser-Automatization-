import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { DashboardPage } from './pages/DashboardPage'
import { ElementMapPage } from './pages/ElementMapPage'
import { HelpPage } from './pages/HelpPage'
import { RoadmapPage } from './pages/RoadmapPage'
import { RunsPage } from './pages/RunsPage'
import { ScenariosPage } from './pages/ScenariosPage'
import { SitesPage } from './pages/SitesPage'
import { TemplatesPage } from './pages/TemplatesPage'
import { MonitorPage } from './pages/MonitorPage'
import { WorkflowPage } from './pages/WorkflowPage'

/** Корневой компонент: общий каркас плюс маршруты разделов. */
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/sites" element={<SitesPage />} />
        <Route path="/element-map" element={<ElementMapPage />} />
        <Route path="/scenarios" element={<ScenariosPage />} />
        <Route path="/templates" element={<TemplatesPage />} />
        <Route path="/workflow" element={<WorkflowPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/monitor" element={<MonitorPage />} />
        <Route path="/help" element={<HelpPage />} />

        <Route path="/roadmap" element={<RoadmapPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
