import type { ReactNode } from 'react'

// Block desktop browsers without mistaking a phone in landscape mode for a PC.
// iPadOS Safari may report a Mac user agent, so also check touch-only devices.
export function isDesktopDevice(): boolean {
  const ua = navigator.userAgent
  const mobile = /Android|iPhone|iPad|iPod|Windows Phone|Mobile|Tablet|Silk|Kindle/i.test(ua)
  const ipadWithDesktopAgent = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1
  const touchOnly = window.matchMedia('(pointer: coarse)').matches &&
    !window.matchMedia('(any-pointer: fine)').matches
  const desktopOS = /Windows NT|Macintosh|Mac OS X|X11|Linux|CrOS/i.test(ua)

  return desktopOS && !mobile && !ipadWithDesktopAgent && !touchOnly
}

export default function DesktopGate({ children }: { children: ReactNode }) {
  const blocked = isDesktopDevice()
  if (!blocked) return <>{children}</>

  return (
    <div className="rateapp-desktop-gate">
      <div className="rateapp-desktop-gate__background" inert aria-hidden="true">
        {children}
      </div>
      <main className="rateapp-desktop-gate__overlay">
        <section className="rateapp-desktop-gate__notice" aria-labelledby="rateapp-desktop-gate-title">
          <span className="rateapp-desktop-gate__emoji" role="img" aria-label="Плачущий смайлик">😢</span>
          <div className="rateapp-desktop-gate__eyebrow">RateApp</div>
          <h1 id="rateapp-desktop-gate-title">Пока только на мобильных</h1>
          <p>RateApp рассчитан на смартфоны. Открой приложение на телефоне, чтобы пользоваться своей библиотекой игр.</p>
          <div className="rateapp-desktop-gate__phones" aria-hidden="true">
            <span>iOS</span>
            <span className="rateapp-desktop-gate__dot" />
            <span>Android</span>
          </div>
        </section>
      </main>
    </div>
  )
}
