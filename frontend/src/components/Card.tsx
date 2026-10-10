import type { ReactNode } from 'react'

/** Карточка-раздел интерфейса. */
export function Card({
  title,
  subtitle,
  actions,
  children,
}: {
  title?: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card__head">
          <div>
            {title ? <h2 className="card__title">{title}</h2> : null}
            {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  )
}

/** Строка «ключ — значение» для панелей со сведениями. */
export function KeyValue({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="kv">
      {items.map(([key, value]) => (
        <div className="kv__row" key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Плашка статуса. */
export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: 'ok' | 'warn' | 'error' | 'neutral' | 'info'
  children: ReactNode
}) {
  return <span className={`chip chip--${tone}`}>{children}</span>
}

/** Заглушка «раздел появится на таком-то этапе». */
export function StagePlaceholder({
  stage,
  title,
  description,
  bullets,
}: {
  stage: string
  title: string
  description: string
  bullets: string[]
}) {
  return (
    <Card title={title} subtitle={description}>
      <div className="placeholder">
        <Badge tone="info">Этап {stage}</Badge>
        <ul className="placeholder__list">
          {bullets.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="muted">
          Раздел станет рабочим после реализации этапа {stage}. Сейчас каркас интерфейса уже
          подключён к API и показывает реальное состояние подсистем.
        </p>
      </div>
    </Card>
  )
}
