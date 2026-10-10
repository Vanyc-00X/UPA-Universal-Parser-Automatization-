import { Badge, Card, KeyValue } from './Card'
import type { ElementMapOut, ElementOut } from '../api/analyzeTypes'
import { formatDateTime, formatNumber } from '../utils/format'

const SOURCE_LABEL: Record<string, string> = {
  heuristic: 'эвристика',
  'heuristic+llm': 'эвристика + ИИ',
  llm: 'ИИ',
  user: 'правка пользователя',
}

/** Цвет плашки по уверенности. */
function confidenceTone(value: number): 'ok' | 'warn' | 'neutral' {
  if (value >= 0.8) return 'ok'
  if (value >= 0.55) return 'warn'
  return 'neutral'
}

/** Плашка уверенности. */
function Confidence({ value }: { value: number }) {
  return <Badge tone={confidenceTone(value)}>{Math.round(value * 100)}%</Badge>
}

/** Один элемент карты: роль, описание, селектор и кандидаты. */
function ElementRow({
  element,
  index,
  onChange,
}: {
  element: ElementOut
  index: number
  onChange: (element: ElementOut, index: number) => void
}) {
  return (
    <tr>
      <td>
        <div className="element__role">
          <strong>{element.label}</strong>
          {element.count > 1 ? <Badge tone="info">×{element.count}</Badge> : null}
        </div>
        <div className="muted small">{element.description}</div>
      </td>
      <td>
        <code className="selector">{element.selector}</code>
        <div className="muted small">
          {SOURCE_LABEL[element.source] ?? element.source} · надёжность селектора{' '}
          {Math.round(element.selector_quality * 100)}%
        </div>
        {element.selectors.length > 1 ? (
          <details className="small">
            <summary className="muted">ещё {element.selectors.length - 1} вариант(ов)</summary>
            <ul className="list list--tight">
              {element.selectors.slice(1).map((candidate) => (
                <li key={candidate.selector}>
                  <code>{candidate.selector}</code>{' '}
                  <span className="muted">
                    {candidate.kind}, {Math.round(candidate.score * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </td>
      <td className="muted small">{element.sample ?? '—'}</td>
      <td>
        <Confidence value={element.confidence} />
      </td>
      <td>
        <button
          type="button"
          className="btn btn--tiny"
          title="Изменить роль или подпись элемента"
          onClick={() => onChange(element, index)}
        >
          правка
        </button>
      </td>
    </tr>
  )
}

/** Панель карты элементов со списком ролей и отчётом. */
export function ElementMapView({
  map,
  onEdit,
  busy,
}: {
  map: ElementMapOut
  onEdit: (element: ElementOut, index: number) => void
  busy: boolean
}) {
  // Индексы нужны для правки: API адресует элемент его позицией в карте.
  const indexed = map.elements.map((element, index) => ({ element, index }))
  const dataElements = indexed.filter(({ element }) => element.count > 1)
  const controlRoles = new Set([
    'search_input',
    'pagination_next',
    'pagination',
    'load_more',
    'filter',
    'sort',
    'submit',
  ])
  const controls = indexed.filter(
    ({ element }) => controlRoles.has(element.role) && element.count <= 1,
  )
  const others = indexed.filter(
    ({ element }) => element.count <= 1 && !controlRoles.has(element.role),
  )

  return (
    <div className="stack">
      <Card
        title={map.page.title || 'Карта элементов'}
        subtitle={`Версия ${map.version} · обновлено ${formatDateTime(map.updated_at)}`}
        actions={
          <div className="btn-row">
            {map.llm.used ? (
              <Badge tone="ok">ИИ: {map.llm.model}</Badge>
            ) : (
              <Badge tone="warn">без ИИ</Badge>
            )}
            {map.edited_by_user ? <Badge tone="info">есть правки</Badge> : null}
          </div>
        }
      >
        <KeyValue
          items={[
            ['Элементов размечено', formatNumber(map.elements.length)],
            ['Источников данных', formatNumber(dataElements.length)],
            [
              'Средняя уверенность',
              map.confidence ? `${Math.round(map.confidence * 100)}%` : '—',
            ],
            ['Групп повторов', formatNumber(map.repeats.length)],
            [
              'ИИ-модель',
              map.llm.used
                ? `${map.llm.provider}:${map.llm.model} (${map.llm.latency_ms} мс)`
                : (map.llm.detail ?? 'не использовалась'),
            ],
            ['Версия промпта', map.prompt_version ?? '—'],
          ]}
        />
        {map.llm.detail && !map.llm.used ? (
          <p className="muted small">
            Роли определены детерминированными эвристиками. Подключите Ollama, чтобы модель
            уточнила формулировки.
          </p>
        ) : null}
      </Card>

      {map.repeats.length > 0 ? (
        <Card
          title="Найденные списки"
          subtitle="Повторяющиеся блоки — карточки товаров, строки таблиц, ленты"
        >
          <table className="table">
            <thead>
              <tr>
                <th>Список</th>
                <th>Элементов</th>
                <th>Похожесть</th>
                <th>Пример</th>
              </tr>
            </thead>
            <tbody>
              {map.repeats.map((group) => (
                <tr key={group.container_path}>
                  <td>
                    <code>
                      &lt;{group.container_tag}
                      {group.container_classes.length > 0
                        ? ` class="${group.container_classes.join(' ')}"`
                        : ''}
                      &gt;
                    </code>
                  </td>
                  <td>
                    {formatNumber(group.count)}
                    {group.collapsed > 0 ? (
                      <span className="muted small">
                        {' '}
                        (в DOM {group.items_in_dom}, скрыто {group.collapsed})
                      </span>
                    ) : null}
                  </td>
                  <td>{Math.round(group.similarity * 100)}%</td>
                  <td className="muted small">{group.sample_text ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      {dataElements.length > 0 ? (
        <Card
          title="Данные, которые можно собирать"
          subtitle="Поля внутри найденных списков; счётчик показывает, сколько записей они покрывают"
        >
          <table className="table">
            <thead>
              <tr>
                <th>Поле</th>
                <th>Селектор</th>
                <th>Пример</th>
                <th>Уверенность</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {dataElements.map(({ element, index }) => (
                <ElementRow
                  key={`${element.role}-${element.selector}-${index}`}
                  element={element}
                  index={index}
                  onChange={onEdit}
                />
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      {controls.length > 0 ? (
        <Card title="Управление страницей" subtitle="Поля, кнопки и переходы">
          <table className="table">
            <thead>
              <tr>
                <th>Элемент</th>
                <th>Селектор</th>
                <th>Пример</th>
                <th>Уверенность</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {controls.map(({ element, index }) => (
                <ElementRow
                  key={`${element.role}-${element.selector}-${index}`}
                  element={element}
                  index={index}
                  onChange={onEdit}
                />
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      {others.length > 0 ? (
        <Card
          title="Прочие элементы"
          subtitle="Заголовки, навигация, шапка и подвал — служебная разметка"
        >
          <ul className="list list--tight">
            {others.map(({ element, index }) => (
              <li key={`${element.role}-${element.selector}-${index}`}>
                <strong>{element.label}</strong>{' '}
                <span className="muted small">{element.description}</span>{' '}
                <code>{element.selector}</code>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {map.report ? (
        <Card title="Отчёт о странице" subtitle="Человекочитаемое описание — его можно показать заказчику">
          <pre className="report">{map.report}</pre>
        </Card>
      ) : null}

      {map.warnings.length > 0 ? (
        <Card title="На что обратить внимание">
          <ul className="list list--tight">
            {map.warnings.map((warning) => (
              <li key={warning} className="muted">
                {warning}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {busy ? <p className="muted">Сохраняю правку…</p> : null}
    </div>
  )
}
