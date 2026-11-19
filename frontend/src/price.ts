const CURRENCY_SYMBOLS: Record<string, string> = {
  EUR: '€',
  INR: '₹',
  USD: '$',
}

function normalizedCurrency(currency: string | null | undefined): string | null {
  const value = currency?.trim()
  return value ? value.toUpperCase() : null
}

export function currencyFromPriceSource(priceSource: string | null | undefined): string | null {
  const match = priceSource?.match(/\(([^)]+)\)/)
  if (match?.[1].trim().toLowerCase() === 'currency unknown') return null
  return normalizedCurrency(match?.[1])
}

export function currencyLabel(currency: string | null | undefined): string {
  const code = normalizedCurrency(currency)
  if (!code) return 'currency unknown'
  const symbol = CURRENCY_SYMBOLS[code]
  return symbol ? `${code} / ${symbol}` : code
}

export function formatPrice(
  amount: number | string | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount === null || amount === undefined || amount === '') return 'Not available'
  const numericAmount = Number(amount)
  if (!Number.isFinite(numericAmount)) return 'Not available'

  const formattedAmount = numericAmount.toFixed(2)
  const code = normalizedCurrency(currency)
  if (!code) return `${formattedAmount} (currency unknown)`

  const symbol = CURRENCY_SYMBOLS[code]
  if (code === 'INR') return `${symbol}${formattedAmount}`
  if (symbol) return `${symbol}${formattedAmount} ${code}`
  return `${formattedAmount} ${code}`
}

export function formatBookPrice(
  amount: number | string | null | undefined,
  priceSource: string | null | undefined,
  priceCurrency?: string | null,
): string {
  // Existing manually entered prices have always used the library's INR default.
  const currency = normalizedCurrency(priceCurrency) || currencyFromPriceSource(priceSource) || (
    priceSource?.includes('currency unknown') ? null : 'INR'
  )
  return formatPrice(amount, currency)
}
