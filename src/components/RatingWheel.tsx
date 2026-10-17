import { useLayoutEffect, useRef } from 'react'
import { useReducedMotion } from 'motion/react'

const RATING_WHEEL_ROW_HEIGHT = 36
const RATING_WHEEL_VALUES = Array.from({ length: 19 }, (_, index) => 1 + index / 2)
const LAST_INDEX = RATING_WHEEL_VALUES.length - 1

// Only the wheel uses half-point increments. Existing historical 0.1 ratings
// in the database are preserved until somebody intentionally edits them.
export const closestHalfPoint = (value: number): number =>
  Math.max(1, Math.min(10, Math.round(value * 2) / 2))

const toIndex = (value: number): number =>
  Math.max(0, Math.min(LAST_INDEX, Math.round((value - 1) * 2)))

export default function RatingWheel({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (value: number) => void
}) {
  const shouldReduceMotion = useReducedMotion()
  const viewportRef = useRef<HTMLDivElement>(null)
  const initializedRef = useRef(false)
  const lastReportedIndexRef = useRef(toIndex(value))
  const selectedIndex = toIndex(value)
  const selectedValue = RATING_WHEEL_VALUES[selectedIndex]

  // Keep controlled values in sync without fighting touch and momentum scrolling.
  useLayoutEffect(() => {
    const index = toIndex(value)
    if (!initializedRef.current || index !== lastReportedIndexRef.current) {
      if (viewportRef.current) viewportRef.current.scrollTop = index * RATING_WHEEL_ROW_HEIGHT
      lastReportedIndexRef.current = index
      initializedRef.current = true
    }
  }, [value])

  const setWheelValue = (index: number, smooth = false) => {
    const nextIndex = Math.min(LAST_INDEX, Math.max(0, index))
    lastReportedIndexRef.current = nextIndex
    onChange(RATING_WHEEL_VALUES[nextIndex])
    viewportRef.current?.scrollTo({
      top: nextIndex * RATING_WHEEL_ROW_HEIGHT,
      behavior: smooth && !shouldReduceMotion ? 'smooth' : 'instant',
    })
  }

  return (
    <div className="rating-wheel">
      <div className="rating-wheel__heading">
        <strong>{label}</strong>
        <b>{selectedValue.toFixed(1)}</b>
      </div>
      <div className="rating-wheel__frame">
        <div
          ref={viewportRef}
          className="rating-wheel__viewport"
          role="spinbutton"
          tabIndex={0}
          aria-label={label}
          aria-valuemin={1}
          aria-valuemax={10}
          aria-valuenow={selectedValue}
          aria-valuetext={selectedValue.toFixed(1)}
          onScroll={(event) => {
            const index = Math.max(0, Math.min(LAST_INDEX, Math.round(event.currentTarget.scrollTop / RATING_WHEEL_ROW_HEIGHT)))
            if (index !== lastReportedIndexRef.current) {
              lastReportedIndexRef.current = index
              onChange(RATING_WHEEL_VALUES[index])
            }
          }}
          onKeyDown={(event) => {
            const current = toIndex(value)
            const next = event.key === 'ArrowDown' ? current + 1
              : event.key === 'ArrowUp' ? current - 1
                : event.key === 'PageDown' ? current + 2
                  : event.key === 'PageUp' ? current - 2
                    : event.key === 'Home' ? 0
                      : event.key === 'End' ? LAST_INDEX : null
            if (next === null) return
            event.preventDefault()
            setWheelValue(next)
          }}
        >
          {RATING_WHEEL_VALUES.map((option, index) => (
            <div
              key={index}
              aria-hidden="true"
              className={selectedIndex === index
                ? 'rating-wheel__item rating-wheel__item--selected'
                : 'rating-wheel__item'}
              onClick={() => setWheelValue(index, true)}
            >
              {option.toFixed(1)}
            </div>
          ))}
        </div>
        <div className="rating-wheel__selection" aria-hidden="true" />
      </div>
    </div>
  )
}
