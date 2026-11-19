import { describe, expect, it, vi } from 'vitest'
import { applyCandidateToForm, emptyRegistrationForm, isStockNumberDuplicate } from './registration'
import { lookupMetadata, MetadataCandidate } from './api'
import { metadataStatusMessageKey } from './registration'

const candidate = (overrides: Partial<MetadataCandidate> = {}): MetadataCandidate => ({
  title: 'Book A',
  isbn: '9780143424123',
  author: 'Author A',
  publisher: 'Publisher A',
  price: 10,
  price_source: 'Fixture',
  price_currency: 'USD',
  source: 'Fixture',
  subjects: [],
  category: 'Fiction',
  subcategory: 'Novel',
  published_date: '2008',
  publication_year: 2008,
  edition: 'First',
  language: 'en',
  page_count: 100,
  description: 'Description A',
  ...overrides,
})

describe('candidate switching', () => {
  it.each([
    ['exact_match', 'metadataExactMatch'],
    ['provider_unavailable', 'metadataProviderUnavailable'],
    ['no_match_found', 'metadataNoMatch'],
    ['conflicting_exact_matches', 'metadataConflictingMatches'],
  ] as const)('maps %s lookup status to a visible message', (status, messageKey) => {
    expect(metadataStatusMessageKey(status)).toBe(messageKey)
  })

  it('reads the overall lookup status and provider diagnostics from response headers', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: {
          'X-Metadata-Result-Status': 'provider_unavailable',
          'X-Metadata-Provider-Status': '{"Google Books":"rate_limited","Open Library":"unavailable"}',
        },
      }),
    )

    await expect(lookupMetadata({ isbn: '9780143424123' })).resolves.toEqual({
      candidates: [],
      status: 'provider_unavailable',
      providerStatus: {
        'Google Books': 'rate_limited',
        'Open Library': 'unavailable',
      },
    })

    fetchMock.mockRestore()
    vi.unstubAllGlobals()
  })

  it('replaces all automatic fields and clears missing values', () => {
    const first = applyCandidateToForm(emptyRegistrationForm, candidate(), new Set())
    const second = applyCandidateToForm(
      first,
      candidate({
        title: 'Book B',
        isbn: '9780306406157',
        author: 'Author B',
        publisher: null,
        price: null,
        price_source: null,
        price_currency: null,
        edition: null,
        description: null,
      }),
      new Set(),
    )

    expect(second.title).toBe('Book B')
    expect(second.author).toBe('Author B')
    expect(second.publisher).toBeNull()
    expect(second.price).toBeNull()
    expect(second.edition).toBeNull()
    expect(second.description).toBeNull()
    expect(second.isbn).toBe('9780306406157')
  })

  it('populates every available candidate field in the save-backed form state', () => {
    const form = applyCandidateToForm(emptyRegistrationForm, candidate(), new Set())

    expect(form).toMatchObject({
      title: 'Book A',
      author: 'Author A',
      publisher: 'Publisher A',
      category: 'Fiction',
      subcategory: 'Novel',
      price: 10,
      price_currency: 'USD',
      published_date: '2008',
      publication_date: '2008',
      publication_year: 2008,
      edition: 'First',
      language: 'en',
      page_count: 100,
      description: 'Description A',
    })
  })

  describe('stock number duplicate warning', () => {
    it('warns for another book but not for the book being edited', () => {
      expect(isStockNumberDuplicate(true, 12, null)).toBe(true)
      expect(isStockNumberDuplicate(true, 12, 12)).toBe(false)
      expect(isStockNumberDuplicate(false, null, null)).toBe(false)
    })
  })

  it('keeps only fields typed by the librarian', () => {
    const first = applyCandidateToForm(emptyRegistrationForm, candidate(), new Set())
    first.stock_number = 'STOCK-1'
    first.title = 'Typed title'
    const second = applyCandidateToForm(
      first,
      candidate({ title: 'Book B', author: null }),
      new Set(['title', 'stock_number']),
    )

    expect(second.stock_number).toBe('STOCK-1')
    expect(second.title).toBe('Typed title')
    expect(second.author).toBeNull()
  })
})
