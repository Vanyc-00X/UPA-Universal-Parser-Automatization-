import { Card } from '../components/Card'

/** Краткая справка со ссылками на docs/ в репозитории. */
export function HelpPage() {
  return (
    <div className="grid">
      <Card title="Справка" subtitle="Документация лежит в каталоге docs/ репозитория">
        <ul className="help-list">
          <li>
            <strong>Быстрый старт</strong> — <code>docs/quickstart.md</code>: запуск, первый
            сценарий, работа без ИИ.
          </li>
          <li>
            <strong>Сценарии</strong> — <code>docs/scenarios.md</code>: сбор, воркфлоу, запись,
            loop/if.
          </li>
          <li>
            <strong>Блокировки</strong> — <code>docs/faq-blocking.md</code>: 403, капча, robots,
            healing.
          </li>
          <li>
            <strong>Данные</strong> — <code>docs/data-retention.md</code>: что хранится локально и
            как чистить.
          </li>
          <li>
            <strong>Дисклеймер</strong> — <code>docs/disclaimer.md</code>: ToS и ответственность за
            live-отправки.
          </li>
        </ul>
        <p className="muted">
          OpenAPI: <a href="/docs" target="_blank" rel="noreferrer">/docs</a> на бэкенде.
        </p>
      </Card>

      <Card title="Типичные ошибки" subtitle="Коротко и по делу">
        <table className="table">
          <thead>
            <tr>
              <th>Ситуация</th>
              <th>Что сделать</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Бэкенд недоступен</td>
              <td>
                Запустите <code>.\run.ps1</code> или <code>launch.cmd</code>
              </td>
            </tr>
            <tr>
              <td>ИИ недоступна</td>
              <td>Продолжайте вручную или «Загрузить модель» на Обзоре / в онбординге</td>
            </tr>
            <tr>
              <td>Пустой снапшот / 403</td>
              <td>
                <code>.\run.ps1 -Headed</code>, логин вручную, см. FAQ
              </td>
            </tr>
            <tr>
              <td>Низкая заполненность</td>
              <td>Запуски → self-healing → применить патч явно</td>
            </tr>
            <tr>
              <td>Live требует confirm</td>
              <td>Отметьте «Подтверждаю опасные действия» на странице Воркфлоу</td>
            </tr>
          </tbody>
        </table>
      </Card>
    </div>
  )
}
