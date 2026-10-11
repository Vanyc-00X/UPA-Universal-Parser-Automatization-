import type { CSSProperties } from 'react'

import type { InspectNodeOut } from '../api/editorTypes'

/** Состояние выбора: подсветка узла и его совпадений с селекторами. */
export interface OverlayHighlight {
  nodeId: string | null
  /** Селектор, который сейчас проверяется: подсвечиваем все его совпадения. */
  selector: string | null
}

/**
 * Оверлей поверх скриншота страницы.
 *
 * Рамки рассчитаны оценкой раскладки (точную геометрию даёт только браузер),
 * поэтому оверлей — это ориентир: он показывает, где находится элемент и какие
 * узлы перехватывает текущий селектор. Точное подтверждение даёт счётчик
 * совпадений в панели проверки.
 */
export function MapOverlay({
  nodes,
  page,
  screenshotUrl,
  highlight,
  onSelect,
  onHover,
}: {
  nodes: InspectNodeOut[]
  page: Record<string, number>
  screenshotUrl: string | null
  highlight: OverlayHighlight
  onSelect: (node: InspectNodeOut) => void
  onHover: (nodeId: string | null) => void
}) {
  const pageWidth = page.width || 1440
  const pageHeight = page.height || 900
  const matches = highlight.selector
    ? nodes.filter((node) => node.matched_by.includes(highlight.selector as string))
    : []

  return (
    <div
      className="overlay"
      style={{ '--page-ratio': `${pageWidth} / ${pageHeight}` } as CSSProperties}
    >
      {screenshotUrl ? (
        <img className="overlay__image" src={screenshotUrl} alt="Скриншот страницы" />
      ) : (
        <div className="overlay__placeholder muted">
          Скриншот недоступен, показаны только рамки элементов
        </div>
      )}

      {/* Совпадения текущего селектора — рисуются под основной подсветкой. */}
      {matches.map((node) => (
        <div
          key={`match-${node.node_id}`}
          className="overlay__box overlay__box--match"
          style={boxStyle(node, pageWidth, pageHeight)}
          title={`Совпадение селектора: ${node.selector}`}
        />
      ))}

      {nodes.map((node) => (
        <button
          type="button"
          key={node.node_id}
          className={
            'overlay__box overlay__box--clickable' +
            (node.node_id === highlight.nodeId ? ' overlay__box--active' : '')
          }
          style={boxStyle(node, pageWidth, pageHeight)}
          title={`${node.label} · ${node.selector}`}
          onClick={() => onSelect(node)}
          onMouseEnter={() => onHover(node.node_id)}
          onMouseLeave={() => onHover(null)}
        >
          <span className="overlay__label">{node.label}</span>
        </button>
      ))}
    </div>
  )
}

/** Преобразует координаты страницы в проценты — оверлей масштабируется сам. */
function boxStyle(
  node: InspectNodeOut,
  pageWidth: number,
  pageHeight: number,
): CSSProperties {
  const box = node.box
  if (!box.width || !box.height) {
    return { display: 'none' }
  }
  return {
    left: `${(box.x / pageWidth) * 100}%`,
    top: `${(box.y / pageHeight) * 100}%`,
    width: `${(box.width / pageWidth) * 100}%`,
    height: `${(box.height / pageHeight) * 100}%`,
  }
}
