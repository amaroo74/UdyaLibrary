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
    clearAuthToken()
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
  author: string | null
  publisher: string | null
  category: string | null
  subcategory: string | null
  price: string | number | null
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
  author?: string
  publisher?: string
  category?: string
  subcategory?: string
  price?: number | null
  price_source?: string | null
  price_confirmed?: boolean
}

export type MetadataCandidate = {
  title: string
  author: string | null
  publisher: string | null
  price: number | null
  price_source: string | null
  source: string
  subjects: string[]
  category: string | null
  subcategory: string | null
}

export type RecognitionResult = {
  success: boolean
  message: string
  barcode: string | null
  ocr_available: boolean
  ocr_lines: string[]
  candidates: MetadataCandidate[]
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
  q?: string
}): Promise<MetadataCandidate[]> {
  const searchParams = new URLSearchParams()
  if (params.isbn) searchParams.set('isbn', params.isbn)
  if (params.title) searchParams.set('title', params.title)
  if (params.author) searchParams.set('author', params.author)
  if (params.q) searchParams.set('q', params.q)

  const response = await fetch(`${API_BASE}/api/recognition/lookup?${searchParams}`, {
    headers: authHeaders(),
  })
  if (!response.ok) {
    return handleResponseError(response, 'Metadata lookup failed')
  }
  return response.json()
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
  const response = await fetch(`${API_BASE}/api/categories`)
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

  const response = await fetch(`${API_BASE}/api/books?${params}`)
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

export function getExportUrl(format: 'csv' | 'xlsx' | 'pdf', filters: BookFilterParams = {}): string {
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

