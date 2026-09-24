import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { SidebarFooter } from './SidebarFooter'

vi.mock('~/stores/gateway', () => ({
  useGateway: () => ({
    status: { state: 'running', url: 'http://localhost:8000', error: '' },
    busy: false,
    start: vi.fn(),
    stop: vi.fn(),
  }),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SidebarFooter', () => {
  it('navigates to a new session when the new-chat button is clicked', () => {
    render(<SidebarFooter />, { wrapper: Wrapper })
    const newBtn = screen.getByTitle('New session')
    expect(newBtn).toBeInTheDocument()
    fireEvent.click(newBtn)
  })

  it('refreshes sessions when the sync button is clicked', () => {
    render(<SidebarFooter />, { wrapper: Wrapper })
    const syncBtn = screen.getByTitle('Sync')
    expect(syncBtn).toBeInTheDocument()
    fireEvent.click(syncBtn)
  })
})
