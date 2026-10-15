import { motion, useReducedMotion } from 'motion/react'

type Props = { progress: number }

// Startup milestones are driven by the actual authentication/bootstrap flow.
// The bar is not an artificial timer that can reach 100% before the API finishes.
export default function LoadingScreen({ progress }: Props) {
  const reduceMotion = useReducedMotion()
  const percent = Math.min(100, Math.max(0, progress))
  const message = percent >= 100
    ? 'Готово!'
    : percent >= 86
      ? 'Подготавливаем вашу библиотеку'
      : percent >= 58
        ? 'Загружаем вашу библиотеку'
        : 'Подключаемся к RateApp'

  return (
    <main className="session-loading" aria-label="Загрузка RateApp">
      <div className="session-loading__space" aria-hidden="true">
        <span className="session-loading__glow session-loading__glow--green" />
        <span className="session-loading__glow session-loading__glow--blue" />
        <span className="session-loading__spark session-loading__spark--one" />
        <span className="session-loading__spark session-loading__spark--two" />
        <span className="session-loading__spark session-loading__spark--three" />
      </div>
      <div className="session-loading__content">
        <motion.div
          className="session-loading__artwork"
          initial={reduceMotion ? false : { opacity: 0, scale: .94, y: 14 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ duration: .58, ease: [0.22, 1, 0.36, 1] }}
        >
          <img
            className="session-loading__art"
            src="/rateapp-splash-art.webp"
            alt="RateApp — игровой контроллер, звезда и коллекция игр"
            fetchPriority="high"
          />
          {!reduceMotion && (
            <motion.span
              className="session-loading__orbit"
              aria-hidden="true"
              animate={{ rotate: 360 }}
              transition={{ duration: 12, ease: 'linear', repeat: Infinity }}
            >
              <span />
            </motion.span>
          )}
        </motion.div>
        <div className="session-loading__footer">
          <p className="session-loading__caption">{message}</p>
          <div
            className="session-loading__progress"
            role="progressbar"
            aria-label="Загрузка приложения"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-valuetext={message}
          >
            <motion.div
              className="session-loading__progress-fill"
              initial={false}
              animate={{ width: `${percent}%` }}
              transition={reduceMotion ? { duration: 0 } : { duration: .38, ease: 'easeOut' }}
            >
              <span className="session-loading__progress-sheen" />
            </motion.div>
          </div>
          <span className="session-loading__percent" aria-hidden="true">{percent}%</span>
        </div>
      </div>
    </main>
  )
}
