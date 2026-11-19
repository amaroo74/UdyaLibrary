import { describe, expect, it } from 'vitest'
import { formatBookPrice, formatPrice } from './price'

describe('price formatting', () => {
  it.each([
    ['INR', '₹500.00'],
    ['USD', '$12.00 USD'],
    ['EUR', '€15.00 EUR'],
    ['XYZ', '20.00 XYZ'],
    [null, '20.00 (currency unknown)'],
  ])('formats %s without inventing a conversion', (currency, expected) => {
    const amount = currency === 'INR' ? 500 : currency === 'USD' ? 12 : currency === 'EUR' ? 15 : 20
    expect(formatPrice(amount, currency)).toBe(expected)
  })

  it('formats missing prices as unavailable', () => {
    expect(formatPrice(null, 'INR')).toBe('Not available')
  })

  it('keeps existing manually entered prices in the INR default', () => {
    expect(formatBookPrice(500, null)).toBe('₹500.00')
  })

  it('preserves unknown currency codes from saved provider sources', () => {
    expect(formatBookPrice(20, 'Google Books (XYZ)')).toBe('20.00 XYZ')
    expect(formatBookPrice(20, 'Google Books (currency unknown)')).toBe('20.00 (currency unknown)')
  })

  it('prefers the persisted ISO currency over legacy source parsing', () => {
    expect(formatBookPrice(12, 'Google Books (USD)', 'EUR')).toBe('€12.00 EUR')
    expect(formatBookPrice(12, null, 'USD')).toBe('$12.00 USD')
  })
})
