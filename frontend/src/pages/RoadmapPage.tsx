import { useQuery } from '@tanstack/react-query'

import { api, queryKeys } from '../api/client'
import { Badge, Card } from '../components/Card'
import type { StageStatus } from '../api/types'

const TONE: Record<StageStatus, 'ok' | 'warn' | 'neutral'> = {
  done: 'ok',
  in_progress: 'warn',
  planned: 'neutral',
}

const LABEL: Record<StageStatus, string> = {
  done: 'готово',
  in_progress: 'в работе',
  planned: 'запланировано',
}

/** План работ: этапы из PLAN.md с их текущим статусом. */
export function RoadmapPage() {
  const roadmap = useQuery({ queryKey: queryKeys.roadmap, queryFn: api.roadmap })

  return (
    <div className="grid">
      <Card
        title="Этапы разработки"
        subtitle="Источник статусов — backend/app/api/system.py"
        actions={roadmap.data ? <Badge tone="info">текущий: этап {roadmap.data.current_stage}</Badge> : null}
      >
        {roadmap.isLoading ? <p className="muted">Загружаю…</p> : null}
        <ol className="timeline">
          {roadmap.data?.stages.map((stage) => (
            <li key={stage.key} className={`timeline__item timeline__item--${stage.status}`}>
              <div className="timeline__head">
                <span className="timeline__num">{stage.key}</span>
                <strong>{stage.title}</strong>
                <Badge tone={TONE[stage.status]}>{LABEL[stage.status]}</Badge>
              </div>
              <ul className="list list--tight">
                {stage.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}
