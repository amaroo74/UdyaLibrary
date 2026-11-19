export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

// Token Management
export function getAuthToken(): string | null {
  return localStorage.getItem('udaya_auth_token')
}

export function setAuthToken(token: string): void {
  localStorage.setItem('udaya_auth_token', token)
}

export function clearAuthToken(): void {
  localStorage.removeItem('udaya_auth_token')
}

export function getDeviceId(): string {
  let devId = localStorage.getItem('udaya_device_id')
  if (!devId) {
    devId = 'dev-' + Math.random().toString(36).substring(2, 10)
    localStorage.setItem('udaya_device_id', devId)
  }
  return devId
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function handleResponseError(response: Response, defaultMsg: string): Promise<never> {
  let message = defaultMsg
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object') {
      const b = body as Record<string, unknown>
      if (typeof b.detail === 'string') {
        message = b.detail
      } else if (Array.isArray(b.detail)) {
        message = b.detail
          .map((d: unknown) => {
            if (typeof d === 'string') return d
            if (d && typeof d === 'object') {
              const item = d as Record<string, unknown>
              const loc = Array.isArray(item.loc)
                ? item.loc.filter(l => l !== 'body').join('.')
                : ''
              const msg = typeof item.msg === 'string' ? item.msg : JSON.stringify(d)
              return loc ? `${loc}: ${msg}` : msg
            }
            return String(d)
          })
          .join('; ')
      } else if (typeof b.message === 'string') {
        message = b.message
      }
    }
  } catch {
    if (response.status === 401) {
      message = 'Authentication required. Please sign in.'
    } else if (response.status === 403) {
      message = 'Access forbidden. You do not have permission for this action.'
    } else if (response.status === 404) {
      message = 'Requested resource was not found.'
    } else if (response.status === 409) {
      message = 'Conflict. This record already exists or was modified elsewhere.'
    } else if (response.status >= 500) {
      message = `Server error (${response.status}). Please try again later.`
    }
  }
  throw new Error(message)
}

export type UserRole = 'administrator' | 'librarian' | 'restricted_librarian'

export type User = {
  id: number
  email: string
  name: string
  role: UserRole
  is_active: boolean
  has_trusted_pin: boolean
  created_at: string
}

export type AuthResponse = {
  access_token: string
  token_type: string
  user: User
}

export type AuditLogEntry = {
  id: number
  entity_type: string
  entity_id: number | null
  action: string
  details: string
  actor: string
  actor_role: string
  device_id: string | null
  created_at: string
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, device_id: getDeviceId() }),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Login failed')
  }
  const data: AuthResponse = await response.json()
  setAuthToken(data.access_token)
  return data
}

export async function loginWithPin(email: string, pin: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/api/auth/pin-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, device_id: getDeviceId(), pin }),
  })
  if (!response.ok) {
    return handleResponseError(response, 'PIN login failed')
  }
  const data: AuthResponse = await response.json()
  setAuthToken(data.access_token)
  return data
}

export async function getMe(): Promise<User> {
  const response = await fetch(`${API_BASE}/api/auth/me`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    if (response.status === 401) {
      clearAuthToken()
    }
    return handleResponseError(response, 'Session expired. Please sign in again.')
  }
  return response.json()
}

export async function setDevicePin(pin: string): Promise<User> {
  const response = await fetch(`${API_BASE}/api/auth/set-pin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ pin, device_id: getDeviceId() }),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not set PIN')
  }
  return response.json()
}

export async function getAuditLogs(): Promise<AuditLogEntry[]> {
  const response = await fetch(`${API_BASE}/api/auth/audit-logs`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not fetch audit logs')
  }
  return response.json()
}

export async function getUsers(): Promise<User[]> {
  const response = await fetch(`${API_BASE}/api/auth/users`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not fetch users')
  }
  return response.json()
}

export async function createUser(user: { email: string; name: string; password: string; role: string }): Promise<User> {
  const response = await fetch(`${API_BASE}/api/auth/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(user),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not create user')
  }
  return response.json()
}

export type Book = {
  id: number
  serial_number: string
  stock_number: string
  title: string
  isbn: string | null
  author: string | null
  publisher: string | null
  publication_date: string | null
  publication_year: number | null
  edition: string | null
  language: string | null
  page_count: number | null
  description: string | null
  category: string | null
  subcategory: string | null
  price: string | number | null
  price_currency: string | null
  price_source: string | null
  price_confirmed: boolean
  created_at: string
  updated_at: string
  is_complete: boolean
  missing_fields: string[]
}

export type BookInput = {
  stock_number: string
  title: string
  isbn?: string | null
  author?: string
  publisher?: string
  publication_date?: string | null
  publication_year?: number | null
  edition?: string | null
  language?: string | null
  page_count?: number | null
  description?: string | null
  category?: string
  subcategory?: string
  price?: number | null
  price_currency?: string | null
  price_source?: string | null
  price_confirmed?: boolean
}

export type MetadataCandidate = {
  title: string
  isbn: string | null
  author: string | null
  publisher: string | null
  price: number | null
  price_source: string | null
  price_currency: string | null
  source: string
  subjects: string[]
  category: string | null
  subcategory: string | null
  published_date?: string | null
  publication_year?: number | null
  edition?: string | null
  language?: string | null
  page_count?: number | null
  description?: string | null
  subtitle?: string | null
  editor?: string | null
  translator?: string | null
  series?: string | null
  volume?: string | null
  cover_image_url?: string | null
  source_url?: string | null
  field_provenance?: Record<string, string[]>
  field_conflicts?: Record<string, Array<string | number | null>>
  local_copy_count?: number | null
  match_status?: string | null
}

export type MetadataLookupStatus =
  | 'exact_match'
  | 'verified_alternative'
  | 'unverified_search'
  | 'provider_unavailable'
  | 'no_match_found'
  | 'conflicting_exact_matches'

export type MetadataLookupResponse = {
  candidates: MetadataCandidate[]
  status: MetadataLookupStatus
  providerStatus: Record<string, string>
}

export type RecognitionResult = {
  success: boolean
  message: string
  barcode: string | null
  ocr_available: boolean
  ocr_lines: string[]
  candidates: MetadataCandidate[]
}

export type StockNumberCheck = {
  stock_number: string
  used: boolean
  title: string | null
  book_id: number | null
}

export async function getStockNumberSuggestion(): Promise<{ stock_number: string }> {
  const response = await fetch(`${API_BASE}/api/books/stock-number/suggestion`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not suggest a stock number')
  }
  return response.json()
}

export async function checkStockNumber(stockNumber: string): Promise<StockNumberCheck> {
  const response = await fetch(
    `${API_BASE}/api/books/stock-number/check?${new URLSearchParams({ stock_number: stockNumber })}`,
    { headers: authHeaders() },
  )
  if (!response.ok) {
    return handleResponseError(response, 'Could not check the stock number')
  }
  return response.json()
}

export async function scanCoverImage(file: File): Promise<RecognitionResult> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE}/api/recognition/scan`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })
  if (!response.ok) {
    return handleResponseError(response, 'Failed to process recognition image')
  }
  return response.json()
}

export async function lookupBarcode(barcode: string): Promise<MetadataCandidate[]> {
  const response = await fetch(`${API_BASE}/api/recognition/barcode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ barcode }),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Failed to lookup barcode')
  }
  return response.json()
}

export async function lookupMetadata(params: {
  isbn?: string
  title?: string
  author?: string
  publisher?: string
  q?: string
}): Promise<MetadataLookupResponse> {
  const searchParams = new URLSearchParams()
  if (params.isbn) searchParams.set('isbn', params.isbn)
  if (params.title) searchParams.set('title', params.title)
  if (params.author) searchParams.set('author', params.author)
  if (params.publisher) searchParams.set('publisher', params.publisher)
  if (params.q) searchParams.set('q', params.q)

  const response = await fetch(`${API_BASE}/api/recognition/lookup?${searchParams}`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Metadata lookup failed')
  }
  const candidates: MetadataCandidate[] = await response.json()
  const headerStatus = response.headers.get('X-Metadata-Result-Status')
  const validStatuses: MetadataLookupStatus[] = [
    'exact_match',
    'verified_alternative',
    'unverified_search',
    'provider_unavailable',
    'no_match_found',
    'conflicting_exact_matches',
  ]
  const status = validStatuses.includes(headerStatus as MetadataLookupStatus)
    ? headerStatus as MetadataLookupStatus
    : candidates.length > 0
      ? 'unverified_search'
      : 'no_match_found'
  let providerStatus: Record<string, string> = {}
  const rawProviderStatus = response.headers.get('X-Metadata-Provider-Status')
  if (rawProviderStatus) {
    try {
      const parsed: unknown = JSON.parse(rawProviderStatus)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        providerStatus = Object.fromEntries(
          Object.entries(parsed).filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
        )
      }
    } catch {
      providerStatus = {}
    }
  }
  return { candidates, status, providerStatus }
}

export type CategoryRead = {
  id: number
  name: string
  parent_id: number | null
}

export type CategoryHierarchy = {
  id: number
  name: string
  subcategories: CategoryRead[]
}

export type BookFilterParams = {
  q?: string
  category?: string
  subcategory?: string
  min_price?: number | null
  max_price?: number | null
  incomplete_only?: boolean
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export async function getCategories(): Promise<CategoryHierarchy[]> {
  const response = await fetch(`${API_BASE}/api/categories`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not load categories')
  }
  return response.json()
}

export async function addCategory(name: string, parent_id?: number | null): Promise<CategoryRead> {
  const response = await fetch(`${API_BASE}/api/categories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ name, parent_id: parent_id || null }),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not save category')
  }
  return response.json()
}

export async function deleteCategory(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/api/categories/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not delete category')
  }
}

export async function getBooks(filters: BookFilterParams = {}): Promise<{ items: Book[]; total: number }> {
  const params = new URLSearchParams()
  params.set('page', String(filters.page || 1))
  params.set('page_size', String(filters.page_size || 200))
  if (filters.q?.trim()) params.set('q', filters.q.trim())
  if (filters.category) params.set('category', filters.category)
  if (filters.subcategory) params.set('subcategory', filters.subcategory)
  if (filters.min_price !== undefined && filters.min_price !== null) params.set('min_price', String(filters.min_price))
  if (filters.max_price !== undefined && filters.max_price !== null) params.set('max_price', String(filters.max_price))
  if (filters.incomplete_only) params.set('incomplete_only', 'true')
  if (filters.sort_by) params.set('sort_by', filters.sort_by)
  if (filters.sort_order) params.set('sort_order', filters.sort_order)

  const response = await fetch(`${API_BASE}/api/books?${params}`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not load the catalogue')
  }
  return response.json()
}

export async function getDeletedBooks(page = 1, page_size = 100): Promise<{ items: Book[]; total: number }> {
  const params = new URLSearchParams({ page: String(page), page_size: String(page_size) })
  const response = await fetch(`${API_BASE}/api/books/deleted?${params}`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not load deleted books')
  }
  return response.json()
}

export async function restoreBook(id: number): Promise<Book> {
  const response = await fetch(`${API_BASE}/api/books/${id}/restore`, {
    method: 'PATCH',
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not restore this book')
  }
  return response.json()
}

export async function addBook(book: BookInput): Promise<Book> {
  const response = await fetch(`${API_BASE}/api/books`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(book),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not save this book')
  }
  return response.json()
}

export async function updateBook(id: number, book: Partial<BookInput>): Promise<Book> {
  const response = await fetch(`${API_BASE}/api/books/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(book),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not update this book')
  }
  return response.json()
}

export async function deleteBook(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/api/books/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not delete this book')
  }
}

// -------------------------------------------------------------
// Phase 7: Bulk Import, Export & Backup API
// -------------------------------------------------------------

export type ImportResult = {
  success: boolean
  total_rows_read: number
  imported_count: number
  error_count: number
  errors: { row: number; error: string; data?: Record<string, unknown> }[]
}

export type BatchRegisterResult = {
  success: boolean
  created_count: number
  error_count: number
  created_items: Book[]
  errors: { stock_number?: string; error: string }[]
}

export type ExportFormat = 'csv' | 'xlsx' | 'pdf'

export function getExportUrl(format: ExportFormat, filters: BookFilterParams = {}): string {
  const params = new URLSearchParams()
  if (filters.q) params.set('q', filters.q)
  if (filters.category) params.set('category', filters.category)
  if (filters.subcategory) params.set('subcategory', filters.subcategory)
  if (filters.min_price !== undefined && filters.min_price !== null) params.set('min_price', String(filters.min_price))
  if (filters.max_price !== undefined && filters.max_price !== null) params.set('max_price', String(filters.max_price))
  if (filters.incomplete_only) params.set('incomplete_only', 'true')
  if (filters.sort_by) params.set('sort_by', filters.sort_by)
  if (filters.sort_order) params.set('sort_order', filters.sort_order)

  return `${API_BASE}/api/bulk/export/${format}?${params.toString()}`
}

function safeDownloadFilename(value: string | null, fallback: string): string {
  if (!value) return fallback

  const encodedFilename = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const quotedFilename = value.match(/filename="([^"]+)"/i)?.[1]
  const plainFilename = value.match(/filename=([^;]+)/i)?.[1]
  const rawFilename = encodedFilename || quotedFilename || plainFilename
  if (!rawFilename) return fallback

  let filename = rawFilename.trim()
  if (encodedFilename) {
    try {
      filename = decodeURIComponent(filename)
    } catch {
      return fallback
    }
  }

  filename = filename
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_')
    .replace(/^\.+/, '')
    .trim()
  return filename || fallback
}

export async function downloadCatalogueExport(
  format: ExportFormat,
  filters: BookFilterParams = {},
): Promise<void> {
  const fallbackFilename = `udaya_library_catalogue.${format}`
  let response: Response

  try {
    response = await fetch(getExportUrl(format, filters), {
      headers: authHeaders(),
    })
  } catch {
    throw new Error('Could not connect to the API to download the export.')
  }

  if (!response.ok) {
    return handleResponseError(response, 'Export download failed')
  }

  let blob: Blob
  try {
    blob = await response.blob()
  } catch {
    throw new Error('The export download could not be read.')
  }

  const objectUrl = URL.createObjectURL(blob)
  const filename = safeDownloadFilename(response.headers.get('Content-Disposition'), fallbackFilename)
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  }
}

export async function importCatalogueFile(file: File): Promise<ImportResult> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE}/api/bulk/import`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })

  if (!response.ok) {
    return handleResponseError(response, 'Failed to import catalogue file')
  }
  return response.json()
}

export async function batchRegisterBooks(books: BookInput[]): Promise<BatchRegisterResult> {
  const response = await fetch(`${API_BASE}/api/bulk/batch-register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(books),
  })

  if (!response.ok) {
    return handleResponseError(response, 'Failed to register batch of books')
  }
  return response.json()
}

export async function downloadDatabaseBackup(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/bulk/backup/download`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Backup download failed. Administrator role required.')
  }
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `udaya_library_backup_${new Date().toISOString().slice(0, 10)}.db`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export async function restoreDatabaseBackup(file: File): Promise<{ success: boolean; message: string; pre_restore_backup?: string }> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE}/api/bulk/backup/restore`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })

  if (!response.ok) {
    return handleResponseError(response, 'Database restore failed')
  }
  return response.json()
}

// -------------------------------------------------------------
// Phase 8: Offline-First Synchronization API
// -------------------------------------------------------------

export type SyncStatus = {
  configured: boolean
  mode: string
  device_id: string
  pending_changes: number
  unresolved_conflicts: number
  last_synced_at: string | null
}

export type SyncConflictItem = {
  id: number
  conflict_id: string
  device_id: string
  entity_type: string
  stock_number: string
  conflict_type: string
  local_data: Partial<BookInput>
  remote_data: Partial<BookInput>
  is_resolved: boolean
  created_at: string | null
}

export async function getSyncStatus(): Promise<SyncStatus> {
  const response = await fetch(`${API_BASE}/api/sync/status`, {
    headers: { ...authHeaders(), 'X-Device-ID': getDeviceId() },
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not fetch synchronization status')
  }
  return response.json()
}

export async function triggerSync(): Promise<{ status: string; pushed?: number; pulled?: number; conflicts_found?: number; message?: string }> {
  const response = await fetch(`${API_BASE}/api/sync/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), 'X-Device-ID': getDeviceId() },
    body: JSON.stringify({}),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Sync trigger failed')
  }
  return response.json()
}

export async function getSyncConflicts(): Promise<SyncConflictItem[]> {
  const response = await fetch(`${API_BASE}/api/sync/conflicts`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not fetch sync conflicts')
  }
  return response.json()
}

export async function resolveSyncConflict(
  conflictId: string,
  strategy: 'KEEP_LOCAL' | 'KEEP_REMOTE' | 'RENAME_STOCK' | 'MANUAL',
  options: { new_stock_number?: string; fields?: Record<string, unknown> } = {}
): Promise<{ status: string; conflict_id: string; strategy: string }> {
  const response = await fetch(`${API_BASE}/api/sync/conflicts/${conflictId}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ strategy, ...options }),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Could not resolve conflict')
  }
  return response.json()
}

