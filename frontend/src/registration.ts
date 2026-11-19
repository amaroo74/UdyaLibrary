import { BookInput, MetadataCandidate, MetadataLookupStatus } from './api'

export type MetadataStatusMessageKey =
  | 'metadataExactMatch'
  | 'metadataVerifiedAlternative'
  | 'metadataUnverifiedSearch'
  | 'metadataProviderUnavailable'
  | 'metadataNoMatch'
  | 'metadataConflictingMatches'

export function metadataStatusMessageKey(status: MetadataLookupStatus): MetadataStatusMessageKey {
  switch (status) {
    case 'exact_match':
      return 'metadataExactMatch'
    case 'verified_alternative':
      return 'metadataVerifiedAlternative'
    case 'provider_unavailable':
      return 'metadataProviderUnavailable'
    case 'conflicting_exact_matches':
      return 'metadataConflictingMatches'
    case 'unverified_search':
      return 'metadataUnverifiedSearch'
    case 'no_match_found':
    default:
      return 'metadataNoMatch'
  }
}

export type RegistrationForm = BookInput & {
  published_date: string | null
  publication_date: string | null
  publication_year: number | null
  edition: string | null
  language: string | null
  page_count: number | null
  description: string | null
  price_currency: string | null
}

export const emptyRegistrationForm: RegistrationForm = {
  stock_number: '',
  title: '',
  author: '',
  publisher: '',
  isbn: null,
  category: '',
  subcategory: '',
  price: null,
  price_source: null,
  price_confirmed: false,
  published_date: null,
  publication_date: null,
  publication_year: null,
  edition: null,
  language: null,
  page_count: null,
  description: null,
  price_currency: null,
}

export function isStockNumberDuplicate(
  used: boolean,
  ownerBookId: number | null,
  editingId: number | null,
): boolean {
  return used && ownerBookId !== editingId
}

function candidateText(value: string | null | undefined): string | null {
  return value?.trim() || null
}

export function applyCandidateToForm(
  current: RegistrationForm,
  candidate: MetadataCandidate,
  manuallyEdited: ReadonlySet<string>,
): RegistrationForm {
  const next = { ...current }
  const setText = (field: keyof RegistrationForm, value: string | null | undefined) => {
    if (!manuallyEdited.has(field)) next[field] = candidateText(value) as never
  }
  const setValue = <K extends keyof RegistrationForm>(field: K, value: RegistrationForm[K]) => {
    if (!manuallyEdited.has(field)) next[field] = value
  }

  setText('title', candidate.title)
  setText('author', candidate.author)
  setText('publisher', candidate.publisher)
  setText('isbn', candidate.isbn)
  const dateManuallyEdited = manuallyEdited.has('published_date') || manuallyEdited.has('publication_date')
  if (!dateManuallyEdited) {
    next.published_date = candidateText(candidate.published_date)
    next.publication_date = candidateText(candidate.published_date)
  }
  setValue('publication_year', candidate.publication_year ?? null)
  setText('edition', candidate.edition)
  setText('language', candidate.language)
  setValue('page_count', candidate.page_count ?? null)
  setText('description', candidate.description)
  setText('category', candidate.category)
  setText('subcategory', candidate.subcategory)
  if (!manuallyEdited.has('price')) {
    next.price = typeof candidate.price === 'number' && Number.isFinite(candidate.price)
      ? candidate.price
      : null
    next.price_confirmed = false
    next.price_source = candidate.price_source
    next.price_currency = candidate.price_currency ?? null
  }
  return next
}
