import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Overview } from './Overview'
import { holding, renderDesk, USDC } from './test-utils'
import type { ProviderId, ProviderStatus, Totals } from './types'

const TOTALS: Totals = {
  valueUsd: 1240.5,
  costUsd: 1000,
  unrealizedUsd: 240.5,
  realizedUsd: -12.25,
  gasUsd: 3.4,
  change24hUsd: 18.75,
  change24hPct: 1.53,
}

function render(
  extra: Partial<Totals> = {},
  opts: { loading?: boolean; syncing?: boolean; unpricedCount?: number } = {},
) {
  const onSync = vi.fn()
  renderDesk(
    <Overview
      unpricedCount={opts.unpricedCount}
      totals={{ ...TOTALS, ...extra }}
      holdings={[
        holding({ token: USDC, valueUsd: 900, allocationPct: 72.5 }),
        holding({
          token: { ...USDC, address: '0xb', symbol: 'WETH' },
          valueUsd: 340.5,
          allocationPct: 27.5,
        }),
      ]}
      syncing={Boolean(opts.syncing)}
      lastSyncAt={Date.now() - 60_000}
      now={Date.now()}
      onSync={onSync}
      loading={Boolean(opts.loading)}
      provider="uniswap"
    />,
  )
  return { onSync }
}

describe('Overview · the desk head', () => {
  it('leads with the value, today as one toned chip, and the four figures', () => {
    render()
    expect(screen.getByTestId('portfolio-value')).toHaveTextContent('$1,240.50')

    const delta = screen.getByTestId('portfolio-delta')
    expect(delta).toHaveAttribute('data-tone', 'up')
    expect(delta).toHaveTextContent('+$18.75')
    expect(delta).toHaveTextContent('+1.53%')

    // Four tiles, each a label over its figure; unrealized also carries a rate.
    expect(screen.getByText('Unrealized').parentElement).toHaveTextContent('+$240.50')
    expect(screen.getByText('Unrealized').parentElement).toHaveTextContent('+24.1%')
    expect(screen.getByText('Realized').parentElement).toHaveTextContent('−$12.25')
    expect(screen.getByText('Cost basis').parentElement).toHaveTextContent('$1,000.00')
    expect(screen.getByText('Gas paid').parentElement).toHaveTextContent('$3.40')
  })

  it('gives every allocation share a legend chip', () => {
    render()
    const legend = screen.getByLabelText('Allocation')
    expect(legend).toHaveTextContent('USDC72.5%')
    expect(legend).toHaveTextContent('WETH27.5%')
  })

  it('says which venue routes, and re-syncs on demand', () => {
    const { onSync } = render()
    expect(screen.getByTestId('provider-pill')).toHaveTextContent('Uniswap')
    fireEvent.click(screen.getByRole('button', { name: 'Resync from chain' }))
    expect(onSync).toHaveBeenCalled()
  })

  it('holds the shape of the head while the figures are still loading', () => {
    render({}, { loading: true })
    expect(screen.queryByTestId('portfolio-delta')).toBeNull()
    expect(screen.getByTestId('portfolio-value')).toBeInTheDocument()
  })

  it('shows a half-cent day as no move at all, not as a win', () => {
    render({ change24hUsd: 0.002, change24hPct: 0.0003 })
    expect(screen.getByTestId('portfolio-delta')).toHaveAttribute('data-tone', 'flat')
  })

  it('colours the head by the book’s PnL, and the chip by the day’s move', () => {
    // Up on the day, but the book as a whole is under water.
    render({ realizedUsd: -30, unrealizedUsd: -70, change24hUsd: 18.75, change24hPct: 2.1 })
    const delta = screen.getByTestId('portfolio-delta')
    expect(delta).toHaveAttribute('data-tone', 'up')
    expect(delta).toHaveAttribute('title', expect.stringContaining('24h price move'))
    expect(screen.getByLabelText('Portfolio value')).toHaveAttribute('data-tone', 'down')
    // And the other way round: a red day on a book that is ahead.
    render({ realizedUsd: 30, unrealizedUsd: 70, change24hUsd: -18.75, change24hPct: -2.1 })
    const [, second] = screen.getAllByLabelText('Portfolio value')
    expect(second).toHaveAttribute('data-tone', 'up')
    expect(second!.querySelector('[data-testid=portfolio-delta]')).toHaveAttribute(
      'data-tone',
      'down',
    )
  })

  it('counts the positions the totals could not price, beside the figure', () => {
    render({}, { unpricedCount: 2 })
    expect(screen.getByTestId('portfolio-unpriced')).toHaveTextContent('2unpriced')
  })

  it('says nothing about unpriced positions when every one has a price', () => {
    render({}, { unpricedCount: 0 })
    expect(screen.queryByTestId('portfolio-unpriced')).toBeNull()
  })
})

const PROVIDER_STATUS: ProviderStatus[] = [
  {
    id: 'aggregator',
    label: 'AgentOS Aggregator',
    needsKey: false,
    keyConfigured: true,
    healthy: null,
  },
  { id: 'uniswap', label: 'Uniswap', needsKey: true, keyConfigured: false, healthy: null },
]

// The venue pill used to be read-only; changing the aggregator meant leaving
// the desk for Settings or the composer. It is the same selector the composer
// seat offers, in place: pick a route, the swap panel follows.
describe('Overview · the provider pill', () => {
  function renderPill(
    props: {
      provider?: ProviderId
      switching?: boolean
      onSwitchProvider?: (id: ProviderId) => void
      onOpenSettings?: () => void
    } = {},
  ) {
    renderDesk(
      <Overview
        totals={TOTALS}
        holdings={[]}
        syncing={false}
        lastSyncAt={null}
        now={Date.now()}
        onSync={vi.fn()}
        loading={false}
        provider={props.provider ?? 'aggregator'}
        providers={PROVIDER_STATUS}
        switching={props.switching}
        onSwitchProvider={props.onSwitchProvider}
        onOpenSettings={props.onOpenSettings}
      />,
    )
  }

  it('switches the route in place, with each choice explained', () => {
    const onSwitch = vi.fn()
    renderPill({ provider: 'aggregator', onSwitchProvider: onSwitch, onOpenSettings: vi.fn() })
    const pill = screen.getByTestId('provider-pill')
    expect(pill).toHaveTextContent('AgentOS Aggregator')
    expect(pill).toHaveAttribute('aria-haspopup', 'menu')
    fireEvent.click(pill)
    const uniswap = screen.getByRole('menuitemradio', { name: /^Uniswap/ })
    expect(uniswap).toHaveTextContent('needs an API key')
    expect(screen.getByRole('menuitemradio', { name: /AgentOS Aggregator/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    fireEvent.click(uniswap)
    expect(onSwitch).toHaveBeenCalledWith('uniswap')
    // Picking the active one is a no-op.
    fireEvent.click(screen.getByTestId('provider-pill'))
    fireEvent.click(screen.getByRole('menuitemradio', { name: /AgentOS Aggregator/ }))
    expect(onSwitch).toHaveBeenCalledTimes(1)
  })

  it('keeps the settings shortcut in the menu', () => {
    const onOpenSettings = vi.fn()
    renderPill({ onOpenSettings })
    fireEvent.click(screen.getByTestId('provider-pill'))
    fireEvent.click(screen.getByRole('menuitem', { name: /Provider settings/ }))
    expect(onOpenSettings).toHaveBeenCalled()
  })

  it('rests disabled while a switch is in flight', () => {
    renderPill({ switching: true, onSwitchProvider: vi.fn() })
    expect(screen.getByTestId('provider-pill')).toBeDisabled()
  })
})
