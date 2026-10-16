import { useLayoutEffect, useRef } from 'react'
import { useReducedMotion } from 'motion/react'

const RATING_WHEEL_ROW_HEIGHT = 36
const RATING_WHEEL_VALUES = Array.from({ length: 91 }, (_, index) => (index + 10) / 10)

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
  const lastReportedTenthsRef = useRef(Math.round(value * 10))

  // Keep controlled values in sync without fighting touch and momentum scrolling.
  useLayoutEffect(() => {
    const tenths = Math.round(value * 10)
    if (!initializedRef.current || tenths !== lastReportedTenthsRef.current) {
      if (viewportRef.current) viewportRef.current.scrollTop = (tenths - 10) * RATING_WHEEL_ROW_HEIGHT
      lastReportedTenthsRef.current = tenths
      initializedRef.current = true
    }
  }, [value])

  const setWheelValue = (tenths: number, smooth = false) => {
    const nextTenths = Math.min(100, Math.max(10, tenths))
    lastReportedTenthsRef.current = nextTenths
    onChange(nextTenths / 10)
    viewportRef.current?.scrollTo({
      top: (nextTenths - 10) * RATING_WHEEL_ROW_HEIGHT,
      behavior: smooth && !shouldReduceMotion ? 'smooth' : 'instant',
    })
  }

  return (
    <div className="rating-wheel">
      <div className="rating-wheel__heading">
        <strong>{label}</strong>
        <b>{value.toFixed(1)}</b>
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
          aria-valuenow={value}
          aria-valuetext={value.toFixed(1)}
          onScroll={(event) => {
            const index = Math.max(0, Math.min(90, Math.round(event.currentTarget.scrollTop / RATING_WHEEL_ROW_HEIGHT)))
            const tenths = index + 10
            if (tenths !== lastReportedTenthsRef.current) {
              lastReportedTenthsRef.current = tenths
              onChange(tenths / 10)
            }
          }}
          onKeyDown={(event) => {
            const current = Math.round(value * 10)
            const next = event.key === 'ArrowDown' ? current + 1
              : event.key === 'ArrowUp' ? current - 1
                : event.key === 'PageDown' ? current + 10
                  : event.key === 'PageUp' ? current - 10
                    : event.key === 'Home' ? 10
                      : event.key === 'End' ? 100 : null
            if (next === null) return
            event.preventDefault()
            setWheelValue(next)
          }}
        >
          {RATING_WHEEL_VALUES.map((option, index) => (
            <div
              key={index}
              aria-hidden="true"
              className={Math.round(value * 10) === index + 10
                ? 'rating-wheel__item rating-wheel__item--selected'
                : 'rating-wheel__item'}
              onClick={() => setWheelValue(index + 10, true)}
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

