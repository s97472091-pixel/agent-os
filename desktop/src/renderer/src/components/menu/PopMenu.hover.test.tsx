import { readFileSync } from 'node:fs'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MenuItem, MenuSub, PopMenu } from './PopMenu'

const css = readFileSync('src/renderer/src/components/menu/menu.css', 'utf8')

function renderMenu() {
  render(
    <PopMenu place={{ at: { x: 10, y: 10 } }} onClose={vi.fn()} label="view">
      <MenuSub label="Grouping">
        <MenuItem label="One" onSelect={vi.fn()} />
      </MenuSub>
    </PopMenu>,
  )
}

const panel = () => screen.queryByRole('menu', { name: 'Grouping' })
const trigger = () => screen.getByRole('menuitem', { name: 'Grouping' })

// The view menu used to feel a beat behind the pointer: the submenu only
// opened after a hard-coded 110ms hover timer and then faded in for another
// 120ms. NSMenu opens the panel the moment the pointer arrives, while still
// tolerating a diagonal move from the row into the panel.
describe('PopMenu submenu hover timing', () => {
  afterEach(() => vi.useRealTimers())

  it('opens the submenu the moment the pointer arrives, with no hover timer', () => {
    renderMenu()
    expect(panel()).toBeNull()
    fireEvent.pointerOver(trigger())
    // Synchronously: any pending timer means the row still feels dead.
    expect(panel()).not.toBeNull()
  })

  it('keeps the diagonal-move grace: a short move away does not close it, the grace does', () => {
    vi.useFakeTimers()
    renderMenu()
    fireEvent.pointerOver(trigger())
    act(() => vi.advanceTimersByTime(250))
    expect(panel()).not.toBeNull()

    // Pointer leaves the submenu for another row of the root menu.
    fireEvent.pointerMove(screen.getByRole('menu', { name: 'view' }))
    expect(panel()).not.toBeNull()
    act(() => vi.advanceTimersByTime(159))
    expect(panel()).not.toBeNull()
    act(() => vi.advanceTimersByTime(2))
    expect(panel()).toBeNull()
  })
})

describe('menu.css entry animations', () => {
  it('drops the submenu entry animation so the panel is there the moment it opens', () => {
    const block = css.match(/\.mac-menu__sub > \.mac-menu \{([\s\S]*?)\}/)?.[1]
    expect(block).toBeDefined()
    expect(block).toMatch(/animation: none/)
  })

  it('shortens the popover entry animation', () => {
    const duration = Number(css.match(/animation: mac-menu-in (\d+)ms/)?.[1])
    expect(duration).toBeGreaterThan(0)
    expect(duration).toBeLessThanOrEqual(80)
  })
})
