import { motion, useReducedMotion } from 'motion/react'

type Props = { progress: number }

// The percentage follows actual startup milestones; it never reaches 100%
// before the bootstrap request finishes.
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
      </div>

      <div className="session-loading__content">
        <motion.div
          className="session-loading__artwork"
          initial={reduceMotion ? false : { opacity: 0, scale: .92, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ duration: .6, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="session-loading__atom" aria-hidden="true">
            <span className="session-loading__orbit session-loading__orbit--green">
              <span className="session-loading__electron" />
            </span>
            <span className="session-loading__orbit session-loading__orbit--cyan">
              <span className="session-loading__electron" />
            </span>
            <span className="session-loading__orbit session-loading__orbit--violet">
              <span className="session-loading__electron" />
            </span>
            <span className="session-loading__star session-loading__star--one" />
            <span className="session-loading__star session-loading__star--two" />
            <span className="session-loading__star session-loading__star--three" />
          </div>
          <img
            className="session-loading__art"
            src="/rateapp-loading-gamepad.avif"
            alt="Светящийся геймпад со звездой и коллекцией игр"
            width={720}
            height={720}
            fetchPriority="high"
            decoding="async"
          />
        </motion.div>

        <h1 className="session-loading__title">RateApp</h1>
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
