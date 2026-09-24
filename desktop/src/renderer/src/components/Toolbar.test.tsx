import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { Toolbar } from './Toolbar'

vi.mock('~/stores/ui', () => ({
  useUi: () => ({
    toggleSidebar: vi.fn(),
    sidebarOpen: true,
    settingsOpen: false,
    openSettings: vi.fn(),
  }),
}))

vi.mock('~/components/UpdatePill', () => ({ UpdatePill: () => null }))

describe('Toolbar', () => {
  it('does not render an inert inspector button', () => {
    render(
      <MemoryRouter>
        <Toolbar />
      </MemoryRouter>,
    )
    expect(screen.queryByLabelText('Inspector')).toBeNull()
    expect(screen.queryByTitle('Inspector')).toBeNull()
  })
})
