import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  addBook,
  addCategory,
  AuditLogEntry,
  batchRegisterBooks,
  BatchRegisterResult,
  Book,
  BookInput,
  CategoryHierarchy,
  clearAuthToken,
  createUser,
  deleteBook,
  deleteCategory,
  downloadCatalogueExport,
  downloadDatabaseBackup,
  ExportFormat,
  getAuditLogs,
  getBooks,
  getCategories,
  getDeletedBooks,
  getMe,
  getStockNumberSuggestion,
  checkStockNumber,
  getSyncConflicts,
  getSyncStatus,
  getUsers,
  importCatalogueFile,
  ImportResult,
  loginUser,
  loginWithPin,
  lookupMetadata,
  MetadataCandidate,
  resolveSyncConflict,
  restoreBook,
  restoreDatabaseBackup,
  scanCoverImage,
  setDevicePin,
  SyncConflictItem,
  SyncStatus,
  triggerSync,
  updateBook,
  User,
} from './api'
import { categoryLabel, Language, t } from './i18n'
import { currencyFromPriceSource, currencyLabel, formatBookPrice, formatPrice } from './price'
import {
  applyCandidateToForm,
  emptyRegistrationForm,
  isStockNumberDuplicate,
  metadataStatusMessageKey,
  RegistrationForm,
} from './registration'

function App() {
  const [lang, setLang] = useState<Language>('en')
  const [activeTab, setActiveTab] = useState<'catalogue' | 'recycle_bin'>('catalogue')
  const [viewMode, setViewMode] = useState<'table' | 'cards'>('table')

  // Auth & User Profile State (Phase 6)
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [loginEmail, setLoginEmail] = useState('admin@udayalibrary.org')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginPin, setLoginPin] = useState('')
  const [usePinMode, setUsePinMode] = useState(false)

  // PIN Setup Modal
  const [showPinModal, setShowPinModal] = useState(false)
  const [newPin, setNewPin] = useState('')

  // Audit Logs Modal
  const [showAuditModal, setShowAuditModal] = useState(false)
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([])

  // Staff Users Modal
  const [showUsersModal, setShowUsersModal] = useState(false)
  const [usersList, setUsersList] = useState<User[]>([])
  const [newUserData, setNewUserData] = useState({
    email: '',
    name: '',
    password: '',
    role: 'librarian',
  })

  // Catalogue data state
  const [books, setBooks] = useState<Book[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // Search & Filter state
  const [query, setQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [selectedSubcategory, setSelectedSubcategory] = useState('')
  const [minPrice, setMinPrice] = useState<string>('')
  const [maxPrice, setMaxPrice] = useState<string>('')
  const [incompleteOnly, setIncompleteOnly] = useState(false)
  const [sortBy, setSortBy] = useState('id')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  // Categories Hierarchy state
  const [categories, setCategories] = useState<CategoryHierarchy[]>([])
  const [showCategoryModal, setShowCategoryModal] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [newSubcatNames, setNewSubcatNames] = useState<Record<number, string>>({})

  // Phase 7: Export, Import & Batch Queue State
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [exportingFormat, setExportingFormat] = useState<ExportFormat | null>(null)
  const [showImportModal, setShowImportModal] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)

  const [showBatchModal, setShowBatchModal] = useState(false)
  const [batchRows, setBatchRows] = useState<BookInput[]>([
    { stock_number: '', title: '', author: '', publisher: '', category: '', subcategory: '', price: null, price_confirmed: false },
  ])
  const [batchSubmitting, setBatchSubmitting] = useState(false)
  const [batchScanningIndex, setBatchScanningIndex] = useState<number | null>(null)

  // Phase 7: Backup & Recovery State (Admin only)
  const [showBackupModal, setShowBackupModal] = useState(false)
  const [backupLoading, setBackupLoading] = useState(false)
  const [restoreFile, setRestoreFile] = useState<File | null>(null)
  const [restoreLoading, setRestoreLoading] = useState(false)

  // Phase 8: Cloud Sync & Conflicts State
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [showConflictsModal, setShowConflictsModal] = useState(false)
  const [conflicts, setConflicts] = useState<SyncConflictItem[]>([])

  // Book registration modal state
  const [form, setForm] = useState<RegistrationForm>(emptyRegistrationForm)
  const manuallyEditedFields = useRef<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [stockDuplicate, setStockDuplicate] = useState<{ title: string | null; bookId: number | null } | null>(null)

  // Recognition state (Phase 4)
  const [candidates, setCandidates] = useState<MetadataCandidate[]>([])
  const [selectedCandidate, setSelectedCandidate] = useState<MetadataCandidate | null>(null)
  const [manualDetailsOpen, setManualDetailsOpen] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanMessage, setScanMessage] = useState('')
  const [onlineQuery, setOnlineQuery] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const onlineSearchInputRef = useRef<HTMLInputElement | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)
  const stockInputRef = useRef<HTMLInputElement | null>(null)

  // Check current session
  const verifySession = useCallback(async () => {
    try {
      const me = await getMe()
      setCurrentUser(me)
    } catch {
      setCurrentUser(null)
    }
  }, [])

  useEffect(() => {
    void verifySession()
  }, [verifySession])

  // Load categories
  const loadCategories = useCallback(async () => {
    try {
      const data = await getCategories()
      setCategories(data)
    } catch {
      // Ignore background category load error
    }
  }, [])

  useEffect(() => {
    void loadCategories()
  }, [loadCategories])

  useEffect(() => {
    if (!showForm || !form.stock_number.trim()) {
      setStockDuplicate(null)
      return
    }
    const timer = window.setTimeout(() => {
      void checkStockNumber(form.stock_number.trim())
        .then(result => {
          setStockDuplicate(
            isStockNumberDuplicate(result.used, result.book_id, editingId)
              ? { title: result.title, bookId: result.book_id }
              : null,
          )
        })
        .catch(err => {
          setError(err instanceof Error ? err.message : 'Could not check the stock number')
        })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [editingId, form.stock_number, showForm])

  // Load cloud sync status (Phase 8)
  const loadSyncStatus = useCallback(async () => {
    try {
      const status = await getSyncStatus()
      setSyncStatus(status)
    } catch {
      // Ignore background sync status error
    }
  }, [])

  useEffect(() => {
    void loadSyncStatus()
  }, [loadSyncStatus])

  // Refresh book list
  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      if (activeTab === 'recycle_bin') {
        const result = await getDeletedBooks(1, 200)
        setBooks(result.items)
        setTotal(result.total)
      } else {
        const result = await getBooks({
          q: query,
          category: selectedCategory || undefined,
          subcategory: selectedSubcategory || undefined,
          min_price: minPrice !== '' ? Number(minPrice) : null,
          max_price: maxPrice !== '' ? Number(maxPrice) : null,
          incomplete_only: incompleteOnly,
          sort_by: sortBy,
          sort_order: sortOrder,
        })
        setBooks(result.items)
        setTotal(result.total)
      }
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to connect to the API')
    } finally {
      setLoading(false)
    }
  }, [
    activeTab,
    query,
    selectedCategory,
    selectedSubcategory,
    minPrice,
    maxPrice,
    incompleteOnly,
    sortBy,
    sortOrder,
  ])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!showForm || editingId !== null) return
    const frame = window.requestAnimationFrame(() => onlineSearchInputRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [showForm, editingId])

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (
        e.key === '/' &&
        document.activeElement !== searchInputRef.current &&
        !showForm &&
        !showCategoryModal &&
        !showLoginModal &&
        !showAuditModal &&
        !showUsersModal
      ) {
        e.preventDefault()
        searchInputRef.current?.focus()
      } else if (e.altKey && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault()
        startAdd()
      } else if (e.key === 'Escape') {
        setShowForm(false)
        setShowCategoryModal(false)
        setShowLoginModal(false)
        setShowAuditModal(false)
        setShowUsersModal(false)
        setShowPinModal(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showForm, showCategoryModal, showLoginModal, showAuditModal, showUsersModal])

  const incompleteCount = useMemo(() => books.filter(book => !book.is_complete).length, [books])

  const filterSubcategories = useMemo(() => {
    if (!selectedCategory) return []
    const match = categories.find(c => c.name.toLowerCase() === selectedCategory.toLowerCase())
    return match ? match.subcategories.map(s => s.name) : []
  }, [categories, selectedCategory])

  const formSubcategories = useMemo(() => {
    if (!form.category) return []
    const match = categories.find(c => c.name.toLowerCase() === form.category?.toLowerCase())
    return match ? match.subcategories.map(s => s.name) : []
  }, [categories, form.category])

  function resolveCategorySelection(candidate: MetadataCandidate): {
    category: string
    subcategory: string
    valid: boolean
  } {
    const suggestedCategory = candidate.category?.trim() || ''
    const suggestedSubcategory = candidate.subcategory?.trim() || ''
    if (!suggestedCategory && !suggestedSubcategory) {
      return { category: '', subcategory: '', valid: true }
    }

    const matchingParents = categories.filter(category =>
      category.subcategories.some(
        subcategory => subcategory.name.toLowerCase() === suggestedSubcategory.toLowerCase(),
      ),
    )
    if (suggestedSubcategory) {
      const parent = categories.find(
        category => category.name.toLowerCase() === suggestedCategory.toLowerCase(),
      )
      const matchingParent = parent
        ? matchingParents.find(category => category.id === parent.id)
        : matchingParents.length === 1
          ? matchingParents[0]
          : undefined
      if (!matchingParent) {
        return { category: '', subcategory: '', valid: false }
      }
      const subcategory = matchingParent.subcategories.find(
        item => item.name.toLowerCase() === suggestedSubcategory.toLowerCase(),
      )
      return subcategory
        ? { category: matchingParent.name, subcategory: subcategory.name, valid: true }
        : { category: '', subcategory: '', valid: false }
    }

    const parent = categories.find(
      category => category.name.toLowerCase() === suggestedCategory.toLowerCase(),
    )
    return parent
      ? { category: parent.name, subcategory: '', valid: true }
      : { category: '', subcategory: '', valid: false }
  }

  // Auth Handlers
  async function handleLogin(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const auth = usePinMode
        ? await loginWithPin(loginEmail.trim(), loginPin.trim())
        : await loginUser(loginEmail.trim(), loginPassword)
      setCurrentUser(auth.user)
      setShowLoginModal(false)
      setNotice(`Welcome, ${auth.user.name} (${auth.user.role}).`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    }
  }

  async function handleExport(format: ExportFormat) {
    setExportingFormat(format)
    setError('')
    try {
      await downloadCatalogueExport(format, {
        q: query,
        category: selectedCategory,
        subcategory: selectedSubcategory,
        min_price: minPrice ? Number(minPrice) : null,
        max_price: maxPrice ? Number(maxPrice) : null,
        incomplete_only: incompleteOnly,
        sort_by: sortBy,
        sort_order: sortOrder,
      })
      setNotice(`Export downloaded (${format.toUpperCase()}).`)
      setShowExportMenu(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export download failed.')
    } finally {
      setExportingFormat(null)
    }
  }

  function handleSignOut() {
    clearAuthToken()
    setCurrentUser(null)
    setNotice('Signed out successfully.')
  }

  async function handleSetDevicePin(e: FormEvent) {
    e.preventDefault()
    if (!newPin.trim()) return
    try {
      const updated = await setDevicePin(newPin.trim())
      setCurrentUser(updated)
      setShowPinModal(false)
      setNewPin('')
      setNotice(t(lang, 'pinSavedNotice'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not set PIN')
    }
  }

  async function handleOpenAuditLogs() {
    try {
      const logs = await getAuditLogs()
      setAuditLogs(logs)
      setShowAuditModal(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not fetch audit history')
    }
  }

  async function handleOpenUsers() {
    try {
      const users = await getUsers()
      setUsersList(users)
      setShowUsersModal(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not fetch staff users')
    }
  }

  async function handleCreateUser(e: FormEvent) {
    e.preventDefault()
    try {
      await createUser(newUserData)
      setNewUserData({ email: '', name: '', password: '', role: 'librarian' })
      const users = await getUsers()
      setUsersList(users)
      setNotice('New staff account added.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create user account')
    }
  }

  // -------------------------------------------------------------
  // Phase 7: Bulk & Backup Handlers
  // -------------------------------------------------------------
  async function handleImportSubmit(e: FormEvent) {
    e.preventDefault()
    if (!importFile) return
    setImporting(true)
    setError('')
    try {
      const res = await importCatalogueFile(importFile)
      setImportResult(res)
      if (res.imported_count > 0) {
        setNotice(`Successfully imported ${res.imported_count} book copies.`)
        await refresh()
        await loadCategories()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  function handleAddBatchRow() {
    setBatchRows(rows => [
      ...rows,
      { stock_number: '', title: '', author: '', publisher: '', category: '', subcategory: '', price: null, price_confirmed: false },
    ])
  }

  function handleRemoveBatchRow(index: number) {
    setBatchRows(rows => rows.filter((_, i) => i !== index))
  }

  function handleBatchRowChange<K extends keyof BookInput>(index: number, key: K, value: BookInput[K]) {
    setBatchRows(rows => {
      const updated = [...rows]
      updated[index] = { ...updated[index], [key]: value }
      return updated
    })
  }

  async function handleBatchScanImage(index: number, file: File) {
    setBatchScanningIndex(index)
    setError('')
    try {
      const res = await scanCoverImage(file)
      if (res.barcode) {
        handleBatchRowChange(index, 'stock_number', res.barcode)
      }
      if (res.candidates && res.candidates.length > 0) {
        const top = res.candidates[0]
        if (top.title) handleBatchRowChange(index, 'title', top.title)
        if (top.author) handleBatchRowChange(index, 'author', top.author)
        if (top.publisher) handleBatchRowChange(index, 'publisher', top.publisher)
        if (top.category) handleBatchRowChange(index, 'category', top.category)
        if (top.subcategory) handleBatchRowChange(index, 'subcategory', top.subcategory)
        if (top.price) handleBatchRowChange(index, 'price', top.price)
      }
      setNotice(`Extracted metadata for row #${index + 1}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Photo scan failed')
    } finally {
      setBatchScanningIndex(null)
    }
  }

  async function handleBatchSubmit() {
    const validRows = batchRows.filter(r => r.stock_number.trim() && r.title.trim())
    if (validRows.length === 0) {
      setError('Please provide at least one row with a unique stock number and book title.')
      return
    }
    setBatchSubmitting(true)
    setError('')
    try {
      const res: BatchRegisterResult = await batchRegisterBooks(validRows)
      if (res.created_count > 0) {
        setNotice(`Registered ${res.created_count} physical book copies.`)
        setShowBatchModal(false)
        setBatchRows([{ stock_number: '', title: '', author: '', publisher: '', category: '', subcategory: '', price: null, price_confirmed: false }])
        await refresh()
        await loadCategories()
      }
      if (res.error_count > 0) {
        setError(`${res.error_count} row(s) failed: ${res.errors.map(e => e.error).join('; ')}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Batch registration failed')
    } finally {
      setBatchSubmitting(false)
    }
  }

  async function handleDownloadBackup() {
    setBackupLoading(true)
    setError('')
    try {
      await downloadDatabaseBackup()
      setNotice('Database backup downloaded successfully.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backup failed')
    } finally {
      setBackupLoading(false)
    }
  }

  async function handleRestoreBackup(e: FormEvent) {
    e.preventDefault()
    if (!restoreFile) return
    if (!window.confirm('Restore database from this backup? Your current database will be safely backed up automatically before restoring.')) return
    setRestoreLoading(true)
    setError('')
    try {
      const res = await restoreDatabaseBackup(restoreFile)
      setNotice(res.message)
      setShowBackupModal(false)
      setRestoreFile(null)
      await refresh()
      await loadCategories()
      await loadSyncStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Database restore failed')
    } finally {
      setRestoreLoading(false)
    }
  }

  // -------------------------------------------------------------
  // Phase 8: Cloud Sync & Conflict Handlers
  // -------------------------------------------------------------
  async function handleTriggerSync() {
    setSyncing(true)
    setError('')
    try {
      const res = await triggerSync()
      if (res.status === 'success') {
        setNotice(`Synchronized: ${res.pushed || 0} pushed, ${res.pulled || 0} pulled.`)
      } else {
        setNotice(res.message || 'Sync completed.')
      }
      await loadSyncStatus()
      await refresh()
      if (res.conflicts_found && res.conflicts_found > 0) {
        await handleOpenConflicts()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  async function handleOpenConflicts() {
    try {
      const data = await getSyncConflicts()
      setConflicts(data)
      setShowConflictsModal(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not fetch conflicts')
    }
  }

  async function handleResolveConflict(conflictId: string, strategy: 'KEEP_LOCAL' | 'KEEP_REMOTE' | 'RENAME_STOCK', newStock?: string) {
    try {
      await resolveSyncConflict(conflictId, strategy, { new_stock_number: newStock })
      setNotice(`Conflict resolved using ${strategy}.`)
      await handleOpenConflicts()
      await loadSyncStatus()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resolve conflict')
    }
  }

  function resetFilters() {
    setQuery('')
    setSelectedCategory('')
    setSelectedSubcategory('')
    setMinPrice('')
    setMaxPrice('')
    setIncompleteOnly(false)
    setSortBy('id')
    setSortOrder('desc')
  }

  function startAdd() {
    setEditingId(null)
    manuallyEditedFields.current.clear()
    setForm(emptyRegistrationForm)
    setError('')
    setCandidates([])
    setSelectedCandidate(null)
    setManualDetailsOpen(false)
    setScanMessage('')
    setOnlineQuery('')
    setShowForm(true)
    void getStockNumberSuggestion()
      .then(result => {
        setForm(current => current.stock_number.trim() ? current : { ...current, stock_number: result.stock_number })
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Could not suggest a stock number'))
  }

  function formFromBook(book: Book): RegistrationForm {
    return {
      stock_number: book.stock_number,
      title: book.title,
      isbn: book.isbn,
      author: book.author || '',
      publisher: book.publisher || '',
      publication_date: book.publication_date || null,
      category: book.category || '',
      subcategory: book.subcategory || '',
      price: book.price === null ? null : Number(book.price),
      price_currency: book.price_currency || currencyFromPriceSource(book.price_source),
      price_source: book.price_source,
      price_confirmed: book.price_confirmed,
      published_date: book.publication_date || null,
      publication_year: book.publication_year,
      edition: book.edition,
      language: book.language,
      page_count: book.page_count,
      description: book.description,
    }
  }

  function startEdit(book: Book) {
    setEditingId(book.id)
    manuallyEditedFields.current.clear()
    setForm(formFromBook(book))
    setError('')
    setCandidates([])
    setSelectedCandidate(null)
    setManualDetailsOpen(true)
    setScanMessage('')
    setOnlineQuery('')
    setShowForm(true)
  }

  function startCopy(book: Book) {
    setEditingId(null)
    manuallyEditedFields.current.clear()
    setForm({ ...formFromBook(book), stock_number: '' })
    setError('')
    setCandidates([])
    setSelectedCandidate(null)
    setManualDetailsOpen(true)
    setScanMessage('')
    setOnlineQuery('')
    setNotice(`${t(lang, 'copyBook')}: "${book.title}".`)
    setShowForm(true)
    void getStockNumberSuggestion()
      .then(result => {
        setForm(current => current.stock_number.trim() ? current : { ...current, stock_number: result.stock_number })
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Could not suggest a stock number'))
  }

  async function handleImageFile(file: File) {
    setScanning(true)
    setScanMessage(t(lang, 'searching'))
    setError('')
    try {
      const result = await scanCoverImage(file)
      setScanMessage(result.message)
      setCandidates(result.candidates)
      if (
        result.candidates.length === 0 &&
        !result.barcode &&
        (!result.ocr_lines || result.ocr_lines.length === 0)
      ) {
        setError(t(lang, 'noBooksDesc'))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to scan image')
      setScanMessage('')
    } finally {
      setScanning(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleOnlineSearch() {
    if (!onlineQuery.trim()) return
    setScanning(true)
    setScanMessage(t(lang, 'searching'))
    setError('')
    try {
      const q = onlineQuery.trim()
      const isDigitsOnly = /^[0-9X-]{9,17}$/i.test(q)
      // Treat the librarian's free-form lookup as a title search. This keeps
      // provider title matching strict and avoids broad keyword results such
      // as translated or unrelated editions outranking the requested book.
      const result = isDigitsOnly
        ? await lookupMetadata({ isbn: q })
        : await lookupMetadata({ title: q, publisher: form.publisher?.trim() || undefined })
      setCandidates(result.candidates)
      setScanMessage(t(lang, metadataStatusMessageKey(result.status), { count: result.candidates.length }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Metadata search failed')
      setScanMessage('')
    } finally {
      setScanning(false)
    }
  }

  function selectCandidate(candidate: MetadataCandidate) {
    const classification = resolveCategorySelection(candidate)
    setForm(current => {
      return applyCandidateToForm(
        current,
        { ...candidate, category: classification.category, subcategory: classification.subcategory },
        manuallyEditedFields.current,
      )
    })
    setSelectedCandidate({ ...candidate })
    setManualDetailsOpen(false)
    setNotice(t(lang, 'useMetadata') + `: "${candidate.title}".`)
    setCandidates([])
    setScanMessage(
      !classification.valid
        ? t(lang, 'classificationNeedsConfirmation')
        : candidate.price === null || candidate.price === undefined
          ? t(lang, 'priceUnavailable')
          : '',
    )
    window.requestAnimationFrame(() => stockInputRef.current?.focus())
  }

  function updateSelectedMetadata<K extends keyof MetadataCandidate>(
    fieldName: K,
    value: MetadataCandidate[K],
  ) {
    setSelectedCandidate(current => (current ? { ...current, [fieldName]: value } : current))
  }

  function updateReviewedCatalogueField<K extends keyof BookInput & keyof MetadataCandidate>(
    fieldName: K,
    value: BookInput[K],
    metadataValue: MetadataCandidate[K & keyof MetadataCandidate],
  ) {
    field(fieldName, value as RegistrationForm[K])
    updateSelectedMetadata(fieldName as K & keyof MetadataCandidate, metadataValue)
  }

  async function submitForm(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    const payload: BookInput = {
      stock_number: form.stock_number.trim(),
      title: form.title.trim(),
      author: form.author?.trim() || undefined,
      publisher: form.publisher?.trim() || undefined,
      category: form.category?.trim() || undefined,
      subcategory: form.subcategory?.trim() || undefined,
      price_source: form.price_source || undefined,
      price_currency: form.price_currency || null,
      price_confirmed: form.price_confirmed,
      price:
        form.price === null || form.price === undefined || Number.isNaN(Number(form.price))
          ? null
          : Number(form.price),
    }
    try {
      if (editingId) {
        await updateBook(editingId, payload)
        setNotice(t(lang, 'saveChanges'))
        setShowForm(false)
        setForm(emptyRegistrationForm)
        setEditingId(null)
      } else {
        await addBook(payload)
        setNotice(`${t(lang, 'saveBook')} ${t(lang, 'addBookModalTitle')}.`)
        setForm(emptyRegistrationForm)
        setCandidates([])
        setSelectedCandidate(null)
        setManualDetailsOpen(false)
        setScanMessage('')
        setOnlineQuery('')
      }
      await refresh()
      await loadCategories()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save book')
    } finally {
      setSaving(false)
    }
  }

  async function removeBook(book: Book) {
    if (currentUser?.role === 'restricted_librarian') {
      setError('Restricted librarians cannot delete books.')
      return
    }
    if (!window.confirm(`Move “${book.title}” (stock ${book.stock_number}) to the recycle bin?`)) return
    try {
      await deleteBook(book.id)
      setNotice(`Moved "${book.title}" to recycle bin.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete book')
    }
  }

  async function handleRestore(book: Book) {
    if (currentUser?.role === 'restricted_librarian') {
      setError('Restricted librarians cannot restore books.')
      return
    }
    try {
      await restoreBook(book.id)
      setNotice(`Restored "${book.title}" to active catalogue.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not restore book')
    }
  }

  // Category Manager CRUD
  async function handleCreateCategory(e: FormEvent) {
    e.preventDefault()
    if (!newCategoryName.trim()) return
    try {
      await addCategory(newCategoryName.trim())
      setNewCategoryName('')
      await loadCategories()
      setNotice('Category added successfully.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add category')
    }
  }

  async function handleCreateSubcategory(parentId: number) {
    const name = newSubcatNames[parentId]?.trim()
    if (!name) return
    try {
      await addCategory(name, parentId)
      setNewSubcatNames(curr => ({ ...curr, [parentId]: '' }))
      await loadCategories()
      setNotice('Subcategory added successfully.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add subcategory')
    }
  }

  async function handleDeleteCategory(catId: number, name: string) {
    if (!window.confirm(t(lang, 'deleteCategoryConfirm', { name }))) return
    try {
      await deleteCategory(catId)
      await loadCategories()
      setNotice(`Deleted category "${name}".`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete category')
    }
  }

  function field<K extends keyof RegistrationForm>(key: K, value: RegistrationForm[K]) {
    manuallyEditedFields.current.add(key)
    setForm(current => {
      const next: RegistrationForm = { ...current }
      next[key] = value
      return next
    })
  }

  return (
    <main className="app-shell">
      {/* Top Header */}
      <header className="topbar">
        <div className="brand-mark">U</div>
        <div className="brand-copy">
          <div className="brand-name">{t(lang, 'appTitle')}</div>
          <div className="brand-subtitle">{t(lang, 'appSubtitle')}</div>
        </div>

        {/* Phase 6: User Status & Auth Control */}
        <div className="user-bar">
          {currentUser ? (
            <div className="user-pill">
              <span>{currentUser.name}</span>
              <span className={`role-badge role-${currentUser.role}`}>{currentUser.role}</span>
              <button
                className="secondary-button"
                style={{ padding: '3px 7px', fontSize: 10 }}
                type="button"
                onClick={() => setShowPinModal(true)}
                title="Configure trusted PIN on this device"
              >
                PIN
              </button>
              <button
                className="secondary-button"
                style={{ padding: '3px 7px', fontSize: 10, color: '#a16d63' }}
                type="button"
                onClick={handleSignOut}
              >
                {t(lang, 'signOut')}
              </button>
            </div>
          ) : (
            <button
              className="primary-button"
              style={{ padding: '7px 12px', fontSize: 11 }}
              type="button"
              onClick={() => setShowLoginModal(true)}
            >
              🔑 {t(lang, 'signIn')}
            </button>
          )}

          {/* Phase 8: Cloud Sync Status Pill */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <button
              className="secondary-button"
              style={{
                padding: '4px 8px',
                fontSize: 11,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                background: syncStatus?.mode === 'cloud_sync' ? '#eef7f0' : '#f5f5f5',
                borderColor: syncStatus?.unresolved_conflicts ? '#c45a4a' : undefined,
              }}
              type="button"
              onClick={() => void handleTriggerSync()}
              disabled={syncing}
              title={`Mode: ${syncStatus?.mode || 'local_only'}. Click to synchronize.`}
            >
              <span>{syncing ? '⏳' : syncStatus?.mode === 'cloud_sync' ? '☁️' : '💾'}</span>
              <span>{syncing ? 'Syncing…' : syncStatus?.mode === 'cloud_sync' ? 'Synced' : 'Local Only'}</span>
              {syncStatus && syncStatus.pending_changes > 0 && (
                <span style={{ background: '#3b7a57', color: '#fff', borderRadius: 10, padding: '1px 5px', fontSize: 10 }}>
                  {syncStatus.pending_changes}
                </span>
              )}
            </button>
            {syncStatus && syncStatus.unresolved_conflicts > 0 && (
              <button
                className="secondary-button"
                style={{ padding: '4px 8px', fontSize: 11, color: '#c45a4a', borderColor: '#c45a4a' }}
                type="button"
                onClick={() => void handleOpenConflicts()}
              >
                ⚠️ {syncStatus.unresolved_conflicts} {t(lang, 'syncConflictsBtn')}
              </button>
            )}
          </div>

          {/* Language Switch */}
          <div className="language-switch" aria-label="Language selector">
            <button
              className={lang === 'en' ? 'language-active' : ''}
              type="button"
              onClick={() => setLang('en')}
            >
              EN
            </button>
            <button
              className={lang === 'ml' ? 'language-active' : ''}
              type="button"
              onClick={() => setLang('ml')}
            >
              മലയാളം
            </button>
          </div>
        </div>
      </header>

      {/* Hero Welcome */}
      <section className="welcome-row">
        <div>
          <p className="eyebrow">{t(lang, 'eyebrow')}</p>
          <h1>{t(lang, 'mainHeading')}</h1>
          <p className="welcome-text">{t(lang, 'welcomeText')}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {/* Admin Exclusive: Audit Trail, Staff & Database Backup */}
          {currentUser?.role === 'administrator' && (
            <>
              <button className="secondary-button" onClick={() => void handleOpenAuditLogs()} type="button">
                {t(lang, 'auditHistoryBtn')}
              </button>
              <button className="secondary-button" onClick={() => void handleOpenUsers()} type="button">
                {t(lang, 'usersBtn')}
              </button>
              <button className="secondary-button" onClick={() => setShowBackupModal(true)} type="button">
                {t(lang, 'backupRestoreBtn')}
              </button>
            </>
          )}

          <button className="secondary-button" onClick={() => setShowImportModal(true)} type="button">
            {t(lang, 'importBtn')}
          </button>
          <button className="secondary-button" onClick={() => setShowBatchModal(true)} type="button">
            {t(lang, 'batchQueueBtn')}
          </button>
          <button className="secondary-button" onClick={() => setShowCategoryModal(true)} type="button">
            {t(lang, 'manageCategoriesBtn')}
          </button>
          <button className="primary-button" onClick={startAdd} type="button">
            {t(lang, 'addBookBtn')}
          </button>
        </div>
      </section>

      {/* Summary Stats */}
      <section className="stats-grid" aria-label="Catalogue summary">
        <div className="stat-card">
          <span className="stat-label">{t(lang, 'totalRecords')}</span>
          <strong>{total}</strong>
          <span className="stat-foot">{t(lang, 'bookCopiesReg')}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">{t(lang, 'needsDetails')}</span>
          <strong>{incompleteCount}</strong>
          <span className="stat-foot">{t(lang, 'visibleResults')}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">{t(lang, 'regRuleTitle')}</span>
          <strong className="stat-word">{t(lang, 'regRuleSub')}</strong>
          <span className="stat-foot">Unique stock number</span>
        </div>
      </section>

      {/* Catalogue Main Panel */}
      <section className="catalogue-panel">
        <div className="catalogue-heading">
          <div>
            <h2>{activeTab === 'catalogue' ? t(lang, 'activeCatalogue') : t(lang, 'recycleBin')}</h2>
            <p>Repeated titles are allowed. Each physical copy gets its own unique stock number.</p>
          </div>
          <div className="view-toggle" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {/* Phase 7: Export Dropdown Menu */}
            <div style={{ position: 'relative' }}>
              <button
                className="secondary-button"
                style={{ padding: '6px 12px', fontSize: 12 }}
                type="button"
                onClick={() => setShowExportMenu(!showExportMenu)}
              >
                {t(lang, 'exportBtn')} ▾
              </button>
              {showExportMenu && (
                <div
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: '100%',
                    background: '#fff',
                    border: '1px solid #dfe5df',
                    borderRadius: 8,
                    boxShadow: '0 4px 14px rgba(0,0,0,0.12)',
                    zIndex: 100,
                    minWidth: 170,
                    padding: 4,
                  }}
                >
                  {([
                    ['csv', '📄', 'exportCsv'],
                    ['xlsx', '📊', 'exportExcel'],
                    ['pdf', '📑', 'exportPdf'],
                  ] as const).map(([format, icon, labelKey]) => (
                    <button
                      key={format}
                      className="secondary-button"
                      type="button"
                      disabled={exportingFormat !== null}
                      style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 12px', border: 0, color: '#1a2e26', fontSize: 12, borderRadius: 4 }}
                      onClick={() => void handleExport(format)}
                    >
                      {exportingFormat === format ? 'Downloading…' : `${icon} ${t(lang, labelKey)}`}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <button
              className={viewMode === 'table' ? 'selected' : ''}
              type="button"
              onClick={() => setViewMode('table')}
            >
              {t(lang, 'viewTable')}
            </button>
            <button
              className={viewMode === 'cards' ? 'selected' : ''}
              type="button"
              onClick={() => setViewMode('cards')}
            >
              {t(lang, 'viewCards')}
            </button>
          </div>
        </div>

        {/* Tab Switcher: Active Catalogue vs Recycle Bin */}
        <div className="catalogue-tabs">
          <button
            className={`tab-btn ${activeTab === 'catalogue' ? 'active' : ''}`}
            type="button"
            onClick={() => setActiveTab('catalogue')}
          >
            {t(lang, 'activeCatalogue')}
          </button>
          <button
            className={`tab-btn ${activeTab === 'recycle_bin' ? 'active' : ''}`}
            type="button"
            onClick={() => setActiveTab('recycle_bin')}
          >
            🗑 {t(lang, 'recycleBin')}
          </button>
        </div>

        {/* Search Row */}
        <div className="search-row">
          <div className="search-box">
            <span>⌕</span>
            <input
              ref={searchInputRef}
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder={t(lang, 'searchPlaceholder')}
              aria-label="Search books"
            />
          </div>
          <button className="secondary-button" type="button" onClick={() => void refresh()}>
            {t(lang, 'refresh')}
          </button>
        </div>

        {/* Advanced Filters & Sorting Bar */}
        {activeTab === 'catalogue' && (
          <div className="filters-bar">
            {/* Category Filter */}
            <select
              className="filter-select"
              value={selectedCategory}
              onChange={e => {
                setSelectedCategory(e.target.value)
                setSelectedSubcategory('')
              }}
            >
              <option value="">{t(lang, 'allCategories')}</option>
              {categories.map(c => (
                <option key={c.id} value={c.name}>
                  {categoryLabel(lang, c.name)}
                </option>
              ))}
            </select>

            {/* Subcategory Filter */}
            {filterSubcategories.length > 0 && (
              <select
                className="filter-select"
                value={selectedSubcategory}
                onChange={e => setSelectedSubcategory(e.target.value)}
              >
                <option value="">{t(lang, 'allSubcategories')}</option>
                {filterSubcategories.map((sub, i) => (
                  <option key={i} value={sub}>
                    {categoryLabel(lang, sub)}
                  </option>
                ))}
              </select>
            )}

            {/* Sorting */}
            <select
              className="filter-select"
              value={`${sortBy}:${sortOrder}`}
              onChange={e => {
                const [sb, so] = e.target.value.split(':')
                setSortBy(sb)
                setSortOrder(so as 'asc' | 'desc')
              }}
            >
              <option value="id:desc">{t(lang, 'sortNewest')}</option>
              <option value="id:asc">{t(lang, 'sortOldest')}</option>
              <option value="title:asc">{t(lang, 'sortTitleAsc')}</option>
              <option value="title:desc">{t(lang, 'sortTitleDesc')}</option>
              <option value="stock_number:asc">{t(lang, 'sortStockAsc')}</option>
              <option value="price:asc">{t(lang, 'sortPriceLow')}</option>
              <option value="price:desc">{t(lang, 'sortPriceHigh')}</option>
            </select>

            {/* Price Range Filter */}
            <input
              className="filter-input"
              type="number"
              min="0"
              placeholder={t(lang, 'minPrice')}
              value={minPrice}
              onChange={e => setMinPrice(e.target.value)}
            />
            <input
              className="filter-input"
              type="number"
              min="0"
              placeholder={t(lang, 'maxPrice')}
              value={maxPrice}
              onChange={e => setMaxPrice(e.target.value)}
            />

            {/* Incomplete Only */}
            <label className="filter-checkbox">
              <input
                type="checkbox"
                checked={incompleteOnly}
                onChange={e => setIncompleteOnly(e.target.checked)}
              />
              {t(lang, 'incompleteOnly')}
            </label>

            {(selectedCategory || selectedSubcategory || minPrice || maxPrice || incompleteOnly || query) && (
              <button
                className="secondary-button"
                style={{ padding: '6px 10px', fontSize: 11 }}
                type="button"
                onClick={resetFilters}
              >
                {t(lang, 'resetFilters')}
              </button>
            )}
          </div>
        )}

        {notice && (
          <div className="notice" role="status">
            {notice}
            <button onClick={() => setNotice('')} type="button">
              ×
            </button>
          </div>
        )}
        {error && (
          <div className="error-banner" role="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
            <div>
              <span>{error}</span>
              {(error.toLowerCase().includes('failed to fetch') || error.toLowerCase().includes('networkerror') || error.toLowerCase().includes('unable to connect')) && (
                <span style={{ display: 'block', marginTop: '0.25rem', fontSize: '0.85em', opacity: 0.9 }}>
                  Check that the backend is running at 127.0.0.1:8000.
                </span>
              )}
            </div>
            <button
              onClick={() => setError('')}
              type="button"
              style={{
                background: 'none',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                fontSize: '1.25rem',
                fontWeight: 'bold',
                padding: '0 0.5rem',
                lineHeight: 1,
              }}
              aria-label="Dismiss error"
            >
              ×
            </button>
          </div>
        )}

        {/* View Mode 1: Table View */}
        {viewMode === 'table' ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, 'serialNo')}</th>
                  <th>{t(lang, 'stockNo')}</th>
                  <th>{t(lang, 'bookTitle')}</th>
                  <th>ISBN</th>
                  <th>{t(lang, 'author')}</th>
                  <th>{t(lang, 'category')}</th>
                  <th>{t(lang, 'price')}</th>
                  <th>{t(lang, 'status')}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={9} className="empty-state">
                      {t(lang, 'searching')}
                    </td>
                  </tr>
                ) : books.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="empty-state">
                      <div className="empty-icon">▤</div>
                      <strong>{t(lang, 'noBooksFound')}</strong>
                      <span>{t(lang, 'noBooksDesc')}</span>
                    </td>
                  </tr>
                ) : (
                  books.map(book => (
                    <tr key={book.id}>
                      <td className="serial-cell">{book.serial_number}</td>
                      <td>{book.stock_number}</td>
                      <td className="title-cell">{book.title}</td>
                      <td>{book.isbn || <span className="missing">{t(lang, 'notEntered')}</span>}</td>
                      <td>{book.author || <span className="missing">{t(lang, 'notEntered')}</span>}</td>
                      <td>
                        {book.category ? (
                          <>
                            {book.category}
                            {book.subcategory ? <small className="subcat">{book.subcategory}</small> : null}
                          </>
                        ) : (
                          <span className="missing">{t(lang, 'notEntered')}</span>
                        )}
                      </td>
                      <td>
                        {formatBookPrice(book.price, book.price_source, book.price_currency)}
                      </td>
                      <td>
                        <span className={book.is_complete ? 'status complete' : 'status incomplete'}>
                          {book.is_complete ? t(lang, 'complete') : t(lang, 'needsDetails')}
                        </span>
                      </td>
                      <td>
                        <div className="row-actions">
                          {activeTab === 'catalogue' ? (
                            <>
                              <button type="button" onClick={() => startEdit(book)} aria-label={`Edit ${book.title}`}>
                                {t(lang, 'edit')}
                              </button>
                              <button type="button" onClick={() => startCopy(book)} aria-label={`${t(lang, 'copyBook')} ${book.title}`}>
                                {t(lang, 'copyBook')}
                              </button>
                              {/* Restricted librarians cannot delete books */}
                              {currentUser?.role !== 'restricted_librarian' && (
                                <button
                                  type="button"
                                  onClick={() => void removeBook(book)}
                                  aria-label={`Delete ${book.title}`}
                                >
                                  {t(lang, 'delete')}
                                </button>
                              )}
                            </>
                          ) : (
                            /* Restricted librarians cannot restore books */
                            currentUser?.role !== 'restricted_librarian' && (
                              <button
                                type="button"
                                style={{ color: '#275941', fontWeight: 700 }}
                                onClick={() => void handleRestore(book)}
                              >
                                ↺ {t(lang, 'restore')}
                              </button>
                            )
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : (
          /* View Mode 2: Card Grid View */
          <div className="cards-grid">
            {loading ? (
              <div className="empty-state" style={{ gridColumn: '1 / -1' }}>
                {t(lang, 'searching')}
              </div>
            ) : books.length === 0 ? (
              <div className="empty-state" style={{ gridColumn: '1 / -1' }}>
                <div className="empty-icon">▤</div>
                <strong>{t(lang, 'noBooksFound')}</strong>
                <span>{t(lang, 'noBooksDesc')}</span>
              </div>
            ) : (
              books.map(book => (
                <div key={book.id} className="book-card">
                  <div>
                    <div className="card-header">
                      <span className="card-serial">{book.serial_number}</span>
                      <span className="card-stock">
                        {t(lang, 'stockNo')}: <b>{book.stock_number}</b>
                      </span>
                    </div>
                    <div className="card-title">{book.title}</div>
                    <div className="card-author">
                      {book.author ? `${t(lang, 'byAuthor')} ${book.author}` : <span className="missing">{t(lang, 'notEntered')}</span>}
                    </div>
                    <div className="card-meta">
                      {book.category && (
                        <span className="card-category">
                          {book.category} {book.subcategory ? `› ${book.subcategory}` : ''}
                        </span>
                      )}
                      <span className="card-price">{formatBookPrice(book.price, book.price_source, book.price_currency)}</span>
                      <span className={book.is_complete ? 'status complete' : 'status incomplete'}>
                        {book.is_complete ? t(lang, 'complete') : t(lang, 'needsDetails')}
                      </span>
                    </div>
                  </div>
                  <div className="card-actions">
                    {activeTab === 'catalogue' ? (
                      <>
                        <button className="secondary-button" style={{ padding: '5px 9px', fontSize: 11 }} type="button" onClick={() => startEdit(book)}>
                          {t(lang, 'edit')}
                        </button>
                        <button className="secondary-button" style={{ padding: '5px 9px', fontSize: 11 }} type="button" onClick={() => startCopy(book)}>
                          {t(lang, 'copyBook')}
                        </button>
                        {currentUser?.role !== 'restricted_librarian' && (
                          <button className="secondary-button" style={{ padding: '5px 9px', fontSize: 11, color: '#a16d63' }} type="button" onClick={() => void removeBook(book)}>
                            {t(lang, 'delete')}
                          </button>
                        )}
                      </>
                    ) : (
                      currentUser?.role !== 'restricted_librarian' && (
                        <button className="primary-button" style={{ padding: '5px 12px', fontSize: 11 }} type="button" onClick={() => void handleRestore(book)}>
                          ↺ {t(lang, 'restore')}
                        </button>
                      )
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        <div className="table-footer">
          <span>{t(lang, 'showingRecords', { count: books.length, total })}</span>
          <span>Press <b>/</b> to search · <b>Alt+N</b> for new book</span>
        </div>
      </section>

      {/* Footer */}
      <footer className="footer">
        <span>{t(lang, 'footerName')}</span>
        <span>{t(lang, 'footerBuild')}</span>
      </footer>

      {/* Book Registration / Edit Modal */}
      {showForm && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={event => {
            if (event.target === event.currentTarget) setShowForm(false)
          }}
        >
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="form-title">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">{t(lang, 'registrationTitle')}</p>
                <h2 id="form-title">
                  {editingId ? t(lang, 'editBookModalTitle') : t(lang, 'addBookModalTitle')}
                </h2>
                <p>{t(lang, 'formSubtitle')}</p>
              </div>
              <button
                className="close-button"
                onClick={() => setShowForm(false)}
                type="button"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* Fast Auto-Fill Section (Phases 3 & 4) */}
            <div className="recognition-box">
              <div className="recognition-title">{t(lang, 'fastAutoFill')}</div>
               <div className="recognition-desc">{t(lang, 'fastAutoFillDesc')}</div>

              <div className="recognition-actions">
                <label className="secondary-button file-upload-btn">
                  <span>{t(lang, 'captureUpload')}</span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    capture="environment"
                    onChange={e => {
                      const f = e.target.files?.[0]
                      if (f) void handleImageFile(f)
                    }}
                  />
                </label>

                <div className="online-search-form">
                  <input
                    ref={onlineSearchInputRef}
                    value={onlineQuery}
                    onChange={e => setOnlineQuery(e.target.value)}
                     placeholder={t(lang, 'lookupOnlinePlaceholder')}
                    disabled={scanning}
                    onKeyDown={event => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        void handleOnlineSearch()
                      }
                    }}
                  />
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={scanning || !onlineQuery.trim()}
                    onClick={() => void handleOnlineSearch()}
                  >
                    {scanning ? t(lang, 'searching') : t(lang, 'lookupBtn')}
                  </button>
                </div>
              </div>

              {scanning && (
                <div className="scan-progress">
                  <span className="spinner"></span>
                  <span>{scanMessage || t(lang, 'searching')}</span>
                </div>
              )}

              {!scanning && scanMessage && (
                <div className="scan-progress" style={{ color: '#44534c' }}>
                  <span>{scanMessage}</span>
                </div>
              )}

              {candidates.length > 0 && (
                <div className="candidates-wrap">
                  <div className="candidates-heading">
                    <span>{t(lang, 'matchingCandidates', { count: candidates.length })}</span>
                    <button
                      type="button"
                      style={{
                        background: 'transparent',
                        border: 0,
                        color: '#88948d',
                        cursor: 'pointer',
                        fontSize: 11,
                      }}
                      onClick={() => setCandidates([])}
                    >
                      {t(lang, 'clearResults')}
                    </button>
                  </div>
                  <div className="candidate-cards">
                    {candidates.map((cand, idx) => (
                      <div key={idx} className="candidate-card">
                        <div className="candidate-info">
                          <div className="candidate-title" title={cand.title}>
                            {cand.title}
                          </div>
                          <div className="candidate-meta">
                            {cand.author && (
                              <span>
                                {t(lang, 'byAuthor')} <b>{cand.author}</b>{' '}
                              </span>
                            )}
                            {cand.publisher && (
                              <span>
                                · {t(lang, 'pubBy')} {cand.publisher}
                              </span>
                            )}
                          </div>
                           {cand.field_conflicts && Object.keys(cand.field_conflicts).length > 0 && (
                             <div className="candidate-description" role="alert">
                               Conflicting values:{' '}
                               {Object.entries(cand.field_conflicts)
                                 .map(([fieldName, values]) => `${fieldName}: ${values.filter(value => value !== null).join(' / ')}`)
                                 .join('; ')}
                             </div>
                           )}
                          <div className="candidate-tags">
                            <span className="tag-price">
                              {formatPrice(cand.price, cand.price_currency)}
                              {cand.price !== null && ` (${t(lang, 'suggestedPrice')})`}
                            </span>
                            {cand.category && (
                              <span
                                className="tag-source"
                                style={{ backgroundColor: '#e8f4fd', color: '#0d47a1', borderColor: '#bbdefb' }}
                                title={`${cand.category}${cand.subcategory ? ` › ${cand.subcategory}` : ''}`}
                              >
                                {categoryLabel(lang, cand.category)}{cand.subcategory ? ` › ${categoryLabel(lang, cand.subcategory)}` : ''}
                              </span>
                            )}
                            <span className="tag-source">{cand.source}</span>
                            {cand.source_url && (
                              <a
                                href={cand.source_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ marginLeft: 6, fontSize: 11, color: '#2b6e49', textDecoration: 'underline' }}
                                title={cand.source_url}
                              >
                                {t(lang, 'viewSource')}
                              </a>
                            )}
                          </div>
                        </div>
                        <button
                          className="select-btn"
                          type="button"
                          onClick={() => selectCandidate(cand)}
                        >
                          {t(lang, 'useMetadata')}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

             {selectedCandidate && !editingId && (
               <div className="confirmed-metadata" role="status">
                 <div>
                   <strong>{selectedCandidate.title}</strong>
                   <span>
                     {[selectedCandidate.author, selectedCandidate.publisher]
                       .filter(Boolean)
                       .join(' · ')}
                   </span>
                 </div>
                   <button className="secondary-button" type="button" onClick={() => setManualDetailsOpen(true)}>
                    {t(lang, 'editMetadata')}
                 </button>
                   <small>{t(lang, 'metadataRetrieved')}</small>
                 <div className="metadata-review-grid">
                   <label>
                     {t(lang, 'bookTitleReq')}
                     <input
                       ref={stockInputRef}
                       required
                       value={form.title}
                       onChange={event => updateReviewedCatalogueField('title', event.target.value, event.target.value)}
                     />
                     <small>{form.title ? t(lang, 'metadataRetrieved') : t(lang, 'metadataMissing')}</small>
                   </label>
                   <label>
                     {t(lang, 'author')}
                     <input
                       value={form.author || ''}
                       onChange={event => updateReviewedCatalogueField('author', event.target.value, event.target.value || null)}
                     />
                     <small>{form.author ? t(lang, 'metadataRetrieved') : t(lang, 'metadataMissing')}</small>
                   </label>
                   <label>
                     {t(lang, 'publisher')}
                     <input
                       value={form.publisher || ''}
                       onChange={event => updateReviewedCatalogueField('publisher', event.target.value, event.target.value || null)}
                     />
                     <small>{form.publisher ? t(lang, 'metadataRetrieved') : t(lang, 'metadataMissing')}</small>
                   </label>
                   <label>
                     {t(lang, 'category')}
                     <select
                       className="filter-select"
                       value={form.category || ''}
                       onChange={event => {
                         field('category', event.target.value)
                         field('subcategory', '')
                         updateSelectedMetadata('category', event.target.value || null)
                         updateSelectedMetadata('subcategory', null)
                       }}
                     >
                       <option value="">{t(lang, 'categorySelect')}</option>
                       {categories.map(category => (
                         <option key={category.id} value={category.name}>{categoryLabel(lang, category.name)}</option>
                       ))}
                     </select>
                     <small>{form.category ? t(lang, 'metadataRetrieved') : t(lang, 'metadataMissing')}</small>
                   </label>
                   <label>
                     {t(lang, 'subcategory')}
                     {formSubcategories.length > 0 ? (
                       <select
                         className="filter-select"
                         value={form.subcategory || ''}
                         onChange={event => updateReviewedCatalogueField('subcategory', event.target.value, event.target.value || null)}
                       >
                         <option value="">{t(lang, 'subcategorySelect')}</option>
                         {formSubcategories.map(subcategory => (
                           <option key={subcategory} value={subcategory}>{categoryLabel(lang, subcategory)}</option>
                         ))}
                       </select>
                     ) : (
                       <input
                         value={form.subcategory || ''}
                         onChange={event => updateReviewedCatalogueField('subcategory', event.target.value, event.target.value || null)}
                         placeholder={t(lang, 'subcategorySelect')}
                       />
                     )}
                     <small>{form.subcategory ? t(lang, 'metadataRetrieved') : t(lang, 'metadataMissing')}</small>
                   </label>
                   <label>
                     {t(lang, 'price')} ({currencyLabel(form.price_currency ?? (selectedCandidate ? null : 'INR'))})
                     <input
                       type="number"
                       min="0"
                       step="0.01"
                       value={form.price ?? ''}
                       onChange={event => {
                         const value = event.target.value === '' ? null : Number(event.target.value)
                         field('price', value)
                         updateSelectedMetadata('price', value)
                       }}
                       placeholder={t(lang, 'pricePlaceholder')}
                     />
                     <small>{form.price !== null && form.price !== undefined ? t(lang, 'metadataRetrieved') : t(lang, 'metadataMissing')}</small>
                   </label>
                 </div>
               </div>
             )}

             {!editingId && !selectedCandidate && !manualDetailsOpen && (
               <div className="manual-fallback" role="status">
                 <span>{t(lang, 'identifyFirst')}</span>
                 <button className="secondary-button" type="button" onClick={() => setManualDetailsOpen(true)}>
                   {t(lang, 'manualEntry')}
                 </button>
               </div>
             )}

             {/* Stock number is always the only required physical-copy entry. */}
            <form onSubmit={event => void submitForm(event)}>
               <div className="form-grid registration-stock-only">
                <label>
                  {t(lang, 'stockNumberReq')}
                  <input
                    required
                    maxLength={100}
                    value={form.stock_number}
                    onChange={event => field('stock_number', event.target.value)}
                    placeholder={t(lang, 'stockPlaceholder')}
                  />
                  {stockDuplicate && (
                    <small role="alert" style={{ color: '#a13b2c' }}>
                      This stock number is already used{stockDuplicate.title ? ` by “${stockDuplicate.title}”` : ''}.
                    </small>
                  )}
                 </label>
               </div>

               {(editingId || manualDetailsOpen) && (
               <div className="form-grid">
                 <label>
                  {t(lang, 'bookTitleReq')}
                  <input
                    required
                    maxLength={500}
                    value={form.title}
                    onChange={event => field('title', event.target.value)}
                    placeholder={t(lang, 'bookTitlePlaceholder')}
                  />
                </label>
                <label>
                  {t(lang, 'author')}
                  <input
                    value={form.author || ''}
                    onChange={event => field('author', event.target.value)}
                    placeholder={t(lang, 'authorPlaceholder')}
                  />
                </label>
                <label>
                  {t(lang, 'publisher')}
                  <input
                    value={form.publisher || ''}
                    onChange={event => field('publisher', event.target.value)}
                    placeholder={t(lang, 'publisherPlaceholder')}
                  />
                </label>

                {/* Hierarchical Category Selector */}
                <label>
                  {t(lang, 'category')}
                  <select
                    className="filter-select"
                    style={{ width: '100%', height: 39 }}
                    value={form.category || ''}
                    onChange={e => {
                      field('category', e.target.value)
                      field('subcategory', '')
                    }}
                  >
                    <option value="">{t(lang, 'categorySelect')}</option>
                    {categories.map(c => (
                      <option key={c.id} value={c.name}>
                        {categoryLabel(lang, c.name)}
                      </option>
                    ))}
                  </select>
                </label>

                {/* Hierarchical Subcategory Selector */}
                <label>
                  {t(lang, 'subcategory')}
                  {formSubcategories.length > 0 ? (
                    <select
                      className="filter-select"
                      style={{ width: '100%', height: 39 }}
                      value={form.subcategory || ''}
                      onChange={e => field('subcategory', e.target.value)}
                    >
                      <option value="">{t(lang, 'subcategorySelect')}</option>
                      {formSubcategories.map((sub, i) => (
                        <option key={i} value={sub}>
                          {categoryLabel(lang, sub)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={form.subcategory || ''}
                      onChange={event => field('subcategory', event.target.value)}
                      placeholder={t(lang, 'subcategorySelect')}
                    />
                  )}
                </label>

                <label>
                  {t(lang, 'price')} ({currencyLabel(form.price_currency ?? 'INR')})
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.price ?? ''}
                    onChange={event =>
                      field('price', event.target.value === '' ? null : Number(event.target.value))
                    }
                    placeholder={t(lang, 'pricePlaceholder')}
                  />
                </label>
              </div>
               )}

               <p className="form-note">{t(lang, 'formNote')}</p>
              {error && <div className="error-banner" role="alert">{error}</div>}

              <div className="modal-actions">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setShowForm(false)}
                >
                  {t(lang, 'cancel')}
                </button>
                 <button className="primary-button" disabled={saving || (!editingId && !form.title.trim())} type="submit">
                  {saving ? t(lang, 'saving') : editingId ? t(lang, 'saveChanges') : t(lang, 'saveBook')}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {/* Category Management Modal */}
      {showCategoryModal && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={e => {
            if (e.target === e.currentTarget) setShowCategoryModal(false)
          }}
        >
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="cat-modal-title">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">HIERARCHY SETTINGS</p>
                <h2 id="cat-modal-title">{t(lang, 'categoriesManagerTitle')}</h2>
                <p>Define standard library categories and subcategories for books.</p>
              </div>
              <button
                className="close-button"
                onClick={() => setShowCategoryModal(false)}
                type="button"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {error && (
              <div className="error-banner" role="alert" style={{ marginBottom: 12 }}>
                {error}
              </div>
            )}

            <div className="category-manager-body">
              <form className="category-add-form" onSubmit={handleCreateCategory}>
                <input
                  required
                  value={newCategoryName}
                  onChange={e => setNewCategoryName(e.target.value)}
                  placeholder={t(lang, 'newCategoryPlaceholder')}
                />
                <button className="primary-button" type="submit">
                  {t(lang, 'addCategory')}
                </button>
              </form>

              <div className="categories-tree">
                {categories.length === 0 ? (
                  <p style={{ color: '#88958c', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                    {t(lang, 'noCategoriesYet')}
                  </p>
                ) : (
                  categories.map(cat => (
                    <div key={cat.id} className="cat-item">
                      <div className="cat-item-header">
                        <span className="cat-item-name">{categoryLabel(lang, cat.name)}</span>
                        <button
                          type="button"
                          className="chip-delete"
                          onClick={() => void handleDeleteCategory(cat.id, cat.name)}
                          title="Delete category"
                        >
                          ✕
                        </button>
                      </div>

                      {cat.subcategories.length > 0 && (
                        <div className="cat-sub-list">
                          {cat.subcategories.map(sub => (
                            <span key={sub.id} className="subcat-chip">
                              {categoryLabel(lang, sub.name)}
                              <button
                                type="button"
                                className="chip-delete"
                                onClick={() => void handleDeleteCategory(sub.id, sub.name)}
                                title="Delete subcategory"
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="add-subcat-row">
                        <input
                          value={newSubcatNames[cat.id] || ''}
                          onChange={e =>
                            setNewSubcatNames(curr => ({ ...curr, [cat.id]: e.target.value }))
                          }
                          placeholder={t(lang, 'newSubcategoryPlaceholder')}
                        />
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => void handleCreateSubcategory(cat.id)}
                        >
                          {t(lang, 'addSubcategory')}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="modal-actions" style={{ marginTop: 20 }}>
              <button
                className="primary-button"
                type="button"
                onClick={() => setShowCategoryModal(false)}
              >
                Done
              </button>
            </div>
          </section>
        </div>
      )}

      {/* Phase 6: Login Modal */}
      {showLoginModal && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={e => {
            if (e.target === e.currentTarget) setShowLoginModal(false)
          }}
        >
          <section className="modal" style={{ maxWidth: 440 }} role="dialog" aria-modal="true">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">AUTHENTICATION</p>
                <h2>{t(lang, 'loginTitle')}</h2>
                <p>{t(lang, 'loginSubtitle')}</p>
              </div>
              <button className="close-button" onClick={() => setShowLoginModal(false)} type="button">
                ×
              </button>
            </div>

            <form onSubmit={e => void handleLogin(e)} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 600 }}>
                {t(lang, 'email')}
                <input
                  required
                  type="email"
                  value={loginEmail}
                  onChange={e => setLoginEmail(e.target.value)}
                  placeholder="admin@udayalibrary.org"
                  style={{ height: 38, border: '1px solid #dfe5df', borderRadius: 7, padding: '0 10px', fontSize: 12 }}
                />
              </label>

              {!usePinMode ? (
                <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 600 }}>
                  {t(lang, 'password')}
                  <input
                    required
                    type="password"
                    value={loginPassword}
                    onChange={e => setLoginPassword(e.target.value)}
                    placeholder="Enter password"
                    style={{ height: 38, border: '1px solid #dfe5df', borderRadius: 7, padding: '0 10px', fontSize: 12 }}
                  />
                </label>
              ) : (
                <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 600 }}>
                  {t(lang, 'devicePin')}
                  <input
                    required
                    type="password"
                    maxLength={8}
                    value={loginPin}
                    onChange={e => setLoginPin(e.target.value)}
                    placeholder="4 to 8 digit PIN"
                    style={{ height: 38, border: '1px solid #dfe5df', borderRadius: 7, padding: '0 10px', fontSize: 12 }}
                  />
                </label>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button
                  type="button"
                  className="login-toggle"
                  onClick={() => setUsePinMode(!usePinMode)}
                >
                  {usePinMode ? t(lang, 'usePasswordInstead') : t(lang, 'usePinInstead')}
                </button>
              </div>

              {error && <div className="error-banner" role="alert">{error}</div>}

              <div className="modal-actions">
                <button className="secondary-button" type="button" onClick={() => setShowLoginModal(false)}>
                  {t(lang, 'cancel')}
                </button>
                <button className="primary-button" type="submit">
                  {usePinMode ? t(lang, 'signInWithPin') : t(lang, 'signIn')}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {/* Phase 6: Set Trusted Device PIN Modal */}
      {showPinModal && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={e => {
            if (e.target === e.currentTarget) setShowPinModal(false)
          }}
        >
          <section className="modal" style={{ maxWidth: 400 }} role="dialog" aria-modal="true">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">TRUSTED DEVICE PIN</p>
                <h2>Set Quick Unlock PIN</h2>
                <p>Configure a 4-8 digit PIN to quickly unlock on this computer without typing your password each time.</p>
              </div>
              <button className="close-button" onClick={() => setShowPinModal(false)} type="button">
                ×
              </button>
            </div>

            <form onSubmit={e => void handleSetDevicePin(e)} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 600 }}>
                Enter new PIN (4-8 digits)
                <input
                  required
                  type="password"
                  maxLength={8}
                  value={newPin}
                  onChange={e => setNewPin(e.target.value)}
                  placeholder="e.g. 1234"
                  style={{ height: 38, border: '1px solid #dfe5df', borderRadius: 7, padding: '0 10px', fontSize: 14 }}
                />
              </label>

              {error && <div className="error-banner" role="alert">{error}</div>}

              <div className="modal-actions">
                <button className="secondary-button" type="button" onClick={() => setShowPinModal(false)}>
                  Cancel
                </button>
                <button className="primary-button" type="submit">
                  Save Device PIN
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {/* Phase 6: Audit History Modal (Admin Only) */}
      {showAuditModal && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={e => {
            if (e.target === e.currentTarget) setShowAuditModal(false)
          }}
        >
          <section className="modal" style={{ maxWidth: 860 }} role="dialog" aria-modal="true">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">SECURITY & AUDIT</p>
                <h2>{t(lang, 'auditLogsTitle')}</h2>
                <p>{t(lang, 'auditLogsDesc')}</p>
              </div>
              <button className="close-button" onClick={() => setShowAuditModal(false)} type="button">
                ×
              </button>
            </div>

            <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
              <table className="audit-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>{t(lang, 'timestamp')}</th>
                    <th>{t(lang, 'actor')}</th>
                    <th>{t(lang, 'role')}</th>
                    <th>{t(lang, 'action')}</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map(log => (
                    <tr key={log.id}>
                      <td style={{ color: '#88948d' }}>#{log.id}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{new Date(log.created_at).toLocaleString()}</td>
                      <td><b>{log.actor}</b></td>
                      <td>
                        <span className={`role-badge role-${log.actor_role}`}>{log.actor_role}</span>
                      </td>
                      <td><code>{log.action}</code></td>
                      <td className="audit-details">{log.details}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {error && <div className="error-banner" role="alert" style={{ marginTop: 12 }}>{error}</div>}

            <div className="modal-actions" style={{ marginTop: 20 }}>
              <button className="primary-button" type="button" onClick={() => setShowAuditModal(false)}>
                Done
              </button>
            </div>
          </section>
        </div>
      )}

      {/* Phase 6: Staff User Management Modal (Admin Only) */}
      {showUsersModal && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={e => {
            if (e.target === e.currentTarget) setShowUsersModal(false)
          }}
        >
          <section className="modal" style={{ maxWidth: 700 }} role="dialog" aria-modal="true">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">STAFF MANAGEMENT</p>
                <h2>{t(lang, 'usersManagementTitle')}</h2>
                <p>{t(lang, 'usersManagementDesc')}</p>
              </div>
              <button className="close-button" onClick={() => setShowUsersModal(false)} type="button">
                ×
              </button>
            </div>

            {/* Add User Form */}
            <form onSubmit={e => void handleCreateUser(e)} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, paddingBottom: 16, borderBottom: '1px solid #eef2ee', marginBottom: 16 }}>
              <label style={{ fontSize: 11, fontWeight: 600 }}>
                Name
                <input
                  required
                  value={newUserData.name}
                  onChange={e => setNewUserData(u => ({ ...u, name: e.target.value }))}
                  placeholder="Librarian name"
                  style={{ width: '100%', height: 35, border: '1px solid #dfe5df', borderRadius: 6, padding: '0 8px', marginTop: 4 }}
                />
              </label>

              <label style={{ fontSize: 11, fontWeight: 600 }}>
                Email
                <input
                  required
                  type="email"
                  value={newUserData.email}
                  onChange={e => setNewUserData(u => ({ ...u, email: e.target.value }))}
                  placeholder="email@udayalibrary.org"
                  style={{ width: '100%', height: 35, border: '1px solid #dfe5df', borderRadius: 6, padding: '0 8px', marginTop: 4 }}
                />
              </label>

              <label style={{ fontSize: 11, fontWeight: 600 }}>
                Password
                <input
                  required
                  type="password"
                  value={newUserData.password}
                  onChange={e => setNewUserData(u => ({ ...u, password: e.target.value }))}
                  placeholder="Password"
                  style={{ width: '100%', height: 35, border: '1px solid #dfe5df', borderRadius: 6, padding: '0 8px', marginTop: 4 }}
                />
              </label>

              <label style={{ fontSize: 11, fontWeight: 600 }}>
                Role
                <select
                  value={newUserData.role}
                  onChange={e => setNewUserData(u => ({ ...u, role: e.target.value }))}
                  style={{ width: '100%', height: 35, border: '1px solid #dfe5df', borderRadius: 6, padding: '0 8px', marginTop: 4, background: '#fff' }}
                >
                  <option value="librarian">Librarian (Standard)</option>
                  <option value="restricted_librarian">Restricted Librarian (No Delete/Restore)</option>
                  <option value="administrator">Administrator (Full Control)</option>
                </select>
              </label>

              <div style={{ gridColumn: 'span 2', display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
                <button className="primary-button" type="submit" style={{ padding: '8px 14px' }}>
                  {t(lang, 'addUserBtn')}
                </button>
              </div>
            </form>

            {/* List Existing Users */}
            <div style={{ maxHeight: 250, overflowY: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: '#f8faf8', textAlign: 'left' }}>
                    <th style={{ padding: 8 }}>Name</th>
                    <th style={{ padding: 8 }}>Email</th>
                    <th style={{ padding: 8 }}>Role</th>
                    <th style={{ padding: 8 }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {usersList.map(u => (
                    <tr key={u.id} style={{ borderTop: '1px solid #edf0ec' }}>
                      <td style={{ padding: 8 }}><b>{u.name}</b></td>
                      <td style={{ padding: 8, color: '#55645c' }}>{u.email}</td>
                      <td style={{ padding: 8 }}>
                        <span className={`role-badge role-${u.role}`}>{u.role}</span>
                      </td>
                      <td style={{ padding: 8 }}>
                        <span style={{ color: u.is_active ? '#2b6e49' : '#a16d63', fontWeight: 600 }}>
                          {u.is_active ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {error && <div className="error-banner" role="alert" style={{ marginTop: 12 }}>{error}</div>}

            <div className="modal-actions" style={{ marginTop: 20 }}>
              <button className="primary-button" type="button" onClick={() => setShowUsersModal(false)}>
                Done
              </button>
            </div>
          </section>
        </div>
      )}

      {/* Phase 7: Import Modal */}
      {showImportModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="modal-card" style={{ maxWidth: 640 }}>
            <div className="modal-header">
              <div>
                <h2>{t(lang, 'importTitle')}</h2>
                <p>{t(lang, 'importSubtitle')}</p>
              </div>
              <button className="close-button" onClick={() => { setShowImportModal(false); setImportResult(null); }} type="button">
                ×
              </button>
            </div>

            <form onSubmit={e => void handleImportSubmit(e)} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>
                Select File (.csv, .xlsx)
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  required
                  onChange={e => {
                    const f = e.target.files?.[0]
                    if (f) setImportFile(f)
                  }}
                  style={{ display: 'block', marginTop: 6 }}
                />
              </label>

              {importResult && (
                <div style={{ background: importResult.error_count > 0 ? '#fff8f6' : '#f0f9f3', border: '1px solid #dfe5df', borderRadius: 8, padding: 12 }}>
                  <p style={{ margin: 0, fontWeight: 600, color: importResult.error_count > 0 ? '#b84233' : '#2b6e49' }}>
                    Read {importResult.total_rows_read} rows: {importResult.imported_count} imported successfully, {importResult.error_count} errors.
                  </p>
                  {importResult.errors.length > 0 && (
                    <div style={{ marginTop: 8, maxHeight: 180, overflowY: 'auto' }}>
                      <table style={{ width: '100%', fontSize: 11 }}>
                        <thead>
                          <tr style={{ textAlign: 'left', color: '#55645c' }}>
                            <th style={{ padding: 4 }}>Row</th>
                            <th style={{ padding: 4 }}>Error</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.errors.map((err, i) => (
                            <tr key={i} style={{ borderTop: '1px solid #feebe7' }}>
                              <td style={{ padding: 4 }}><b>#{err.row}</b></td>
                              <td style={{ padding: 4, color: '#b84233' }}>{err.error}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {error && <div className="error-banner" role="alert">{error}</div>}

              <div className="modal-actions" style={{ marginTop: 10 }}>
                <button className="secondary-button" type="button" onClick={() => { setShowImportModal(false); setImportResult(null); }}>
                  {t(lang, 'cancel')}
                </button>
                <button className="primary-button" type="submit" disabled={importing || !importFile}>
                  {importing ? 'Importing…' : 'Start Import'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {/* Phase 7: Batch Scanning & Registration Queue Modal */}
      {showBatchModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="modal-card" style={{ maxWidth: 960, width: '95vw' }}>
            <div className="modal-header">
              <div>
                <h2>{t(lang, 'batchQueueTitle')}</h2>
                <p>{t(lang, 'batchQueueSubtitle')}</p>
              </div>
              <button className="close-button" onClick={() => setShowBatchModal(false)} type="button">
                ×
              </button>
            </div>

            <div style={{ maxHeight: 380, overflowY: 'auto', marginBottom: 14 }}>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#f4f6f4', textAlign: 'left' }}>
                    <th style={{ padding: 6 }}>#</th>
                    <th style={{ padding: 6 }}>Stock No. *</th>
                    <th style={{ padding: 6 }}>Book Title *</th>
                    <th style={{ padding: 6 }}>Author</th>
                    <th style={{ padding: 6 }}>Category</th>
                    <th style={{ padding: 6 }}>Price</th>
                    <th style={{ padding: 6 }}>Scan Photo</th>
                    <th style={{ padding: 6 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {batchRows.map((row, idx) => (
                    <tr key={idx} style={{ borderTop: '1px solid #edf0ec' }}>
                      <td style={{ padding: 6 }}>{idx + 1}</td>
                      <td style={{ padding: 4 }}>
                        <input
                          required
                          value={row.stock_number}
                          onChange={e => handleBatchRowChange(idx, 'stock_number', e.target.value)}
                          placeholder="Unique stock"
                          style={{ width: 110, height: 30, border: '1px solid #dfe5df', borderRadius: 4, padding: '0 6px' }}
                        />
                      </td>
                      <td style={{ padding: 4 }}>
                        <input
                          required
                          value={row.title}
                          onChange={e => handleBatchRowChange(idx, 'title', e.target.value)}
                          placeholder="Title"
                          style={{ width: 180, height: 30, border: '1px solid #dfe5df', borderRadius: 4, padding: '0 6px' }}
                        />
                      </td>
                      <td style={{ padding: 4 }}>
                        <input
                          value={row.author || ''}
                          onChange={e => handleBatchRowChange(idx, 'author', e.target.value)}
                          placeholder="Author"
                          style={{ width: 130, height: 30, border: '1px solid #dfe5df', borderRadius: 4, padding: '0 6px' }}
                        />
                      </td>
                      <td style={{ padding: 4 }}>
                        <input
                          value={row.category || ''}
                          onChange={e => handleBatchRowChange(idx, 'category', e.target.value)}
                          placeholder="Category"
                          style={{ width: 110, height: 30, border: '1px solid #dfe5df', borderRadius: 4, padding: '0 6px' }}
                        />
                      </td>
                      <td style={{ padding: 4 }}>
                        <input
                          type="number"
                          value={row.price ?? ''}
                          onChange={e => handleBatchRowChange(idx, 'price', e.target.value ? Number(e.target.value) : null)}
                          placeholder="Amount"
                          style={{ width: 75, height: 30, border: '1px solid #dfe5df', borderRadius: 4, padding: '0 6px' }}
                        />
                      </td>
                      <td style={{ padding: 4 }}>
                        <label className="secondary-button" style={{ padding: '3px 8px', fontSize: 10, cursor: 'pointer', display: 'inline-block' }}>
                          {batchScanningIndex === idx ? '⏳' : '📷 Scan'}
                          <input
                            type="file"
                            accept="image/*"
                            capture="environment"
                            style={{ display: 'none' }}
                            onChange={e => {
                              const file = e.target.files?.[0]
                              if (file) void handleBatchScanImage(idx, file)
                            }}
                          />
                        </label>
                      </td>
                      <td style={{ padding: 4 }}>
                        {batchRows.length > 1 && (
                          <button
                            type="button"
                            onClick={() => handleRemoveBatchRow(idx)}
                            style={{ background: 'none', border: 'none', color: '#c45a4a', cursor: 'pointer', fontSize: 16 }}
                            title="Remove row"
                          >
                            ×
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {error && <div className="error-banner" role="alert" style={{ marginBottom: 12 }}>{error}</div>}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button className="secondary-button" type="button" onClick={handleAddBatchRow}>
                + Add Row
              </button>
              <div className="modal-actions" style={{ margin: 0 }}>
                <button className="secondary-button" type="button" onClick={() => setShowBatchModal(false)}>
                  {t(lang, 'cancel')}
                </button>
                <button className="primary-button" type="button" onClick={() => void handleBatchSubmit()} disabled={batchSubmitting}>
                  {batchSubmitting ? 'Registering…' : `Register ${batchRows.filter(r => r.stock_number && r.title).length} Copies`}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* Phase 7: Admin Database Backup & Restore Modal */}
      {showBackupModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="modal-card" style={{ maxWidth: 540 }}>
            <div className="modal-header">
              <div>
                <h2>{t(lang, 'backupTitle')}</h2>
                <p>Download a verified SQLite snapshot or restore from a safe backup.</p>
              </div>
              <button className="close-button" onClick={() => setShowBackupModal(false)} type="button">
                ×
              </button>
            </div>

            {error && (
              <div className="error-banner" role="alert" style={{ marginBottom: 16 }}>
                {error}
              </div>
            )}

            {/* Section 1: Hot Download */}
            <div style={{ padding: '12px 14px', background: '#f6f9f7', border: '1px solid #dce8e0', borderRadius: 8, marginBottom: 16 }}>
              <h3 style={{ fontSize: 13, margin: '0 0 6px 0' }}>1. Download Hot Database Backup</h3>
              <p style={{ fontSize: 11, color: '#55645c', margin: '0 0 10px 0' }}>
                Creates an exact, verified point-in-time snapshot of the SQLite catalogue database.
              </p>
              <button className="primary-button" type="button" onClick={() => void handleDownloadBackup()} disabled={backupLoading}>
                {backupLoading ? 'Downloading…' : 'Download Snapshot (.db)'}
              </button>
            </div>

            {/* Section 2: Safe Restore */}
            <form onSubmit={e => void handleRestoreBackup(e)} style={{ padding: '12px 14px', background: '#fff9f8', border: '1px solid #fae6e3', borderRadius: 8 }}>
              <h3 style={{ fontSize: 13, margin: '0 0 6px 0', color: '#8a3429' }}>2. Restore from Backup File</h3>
              <p style={{ fontSize: 11, color: '#7a5a54', margin: '0 0 10px 0' }}>
                Before restoring, the system automatically archives your current active database to a timestamped <code>.bak</code> file to ensure zero data loss.
              </p>
              <input
                type="file"
                accept=".db,.bak"
                required
                onChange={e => {
                  const f = e.target.files?.[0]
                  if (f) setRestoreFile(f)
                }}
                style={{ fontSize: 11, marginBottom: 12, display: 'block' }}
              />
              <button className="secondary-button" type="submit" disabled={restoreLoading || !restoreFile} style={{ borderColor: '#c45a4a', color: '#a13b2c' }}>
                {restoreLoading ? 'Restoring…' : 'Restore Database'}
              </button>
            </form>

            <div className="modal-actions" style={{ marginTop: 16 }}>
              <button className="secondary-button" type="button" onClick={() => setShowBackupModal(false)}>
                Done
              </button>
            </div>
          </section>
        </div>
      )}

      {/* Phase 8: Cloud Sync Conflicts Modal */}
      {showConflictsModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="modal-card" style={{ maxWidth: 720 }}>
            <div className="modal-header">
              <div>
                <h2>{t(lang, 'conflictsTitle')}</h2>
                <p>Concurrent modifications detected. Choose how to resolve each conflict safely.</p>
              </div>
              <button className="close-button" onClick={() => setShowConflictsModal(false)} type="button">
                ×
              </button>
            </div>

            {error && (
              <div className="error-banner" role="alert" style={{ marginBottom: 16 }}>
                {error}
              </div>
            )}

            {conflicts.length === 0 ? (
              <p style={{ color: '#2b6e49', padding: '16px 0' }}>No unresolved conflicts! All records are in sync.</p>
            ) : (
              <div style={{ maxHeight: 380, overflowY: 'auto' }}>
                {conflicts.map(c => (
                  <div key={c.conflict_id} style={{ border: '1px solid #e8ede8', borderRadius: 8, padding: 12, marginBottom: 12, background: '#fdfefe' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>Stock #{c.stock_number}</span>
                      <span style={{ fontSize: 11, background: '#fae6e3', color: '#a13b2c', borderRadius: 4, padding: '2px 6px' }}>
                        {c.conflict_type}
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11, background: '#f8faf8', padding: 8, borderRadius: 6 }}>
                      <div>
                        <b>Local Copy:</b>
                        <div>Title: {c.local_data.title || '—'}</div>
                        <div>Author: {c.local_data.author || '—'}</div>
                        <div>Price: {formatBookPrice(c.local_data.price, c.local_data.price_source || null, c.local_data.price_currency || null)}</div>
                      </div>
                      <div>
                        <b>Remote Copy:</b>
                        <div>Title: {c.remote_data.title || '—'}</div>
                        <div>Author: {c.remote_data.author || '—'}</div>
                        <div>Price: {formatBookPrice(c.remote_data.price, c.remote_data.price_source || null, c.remote_data.price_currency || null)}</div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
                      <button
                        className="secondary-button"
                        type="button"
                        style={{ fontSize: 11, padding: '4px 10px' }}
                        onClick={() => void handleResolveConflict(c.conflict_id, 'KEEP_LOCAL')}
                      >
                        Keep Local
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        style={{ fontSize: 11, padding: '4px 10px' }}
                        onClick={() => void handleResolveConflict(c.conflict_id, 'KEEP_REMOTE')}
                      >
                        Keep Remote
                      </button>
                      <button
                        className="primary-button"
                        type="button"
                        style={{ fontSize: 11, padding: '4px 10px' }}
                        onClick={() => {
                          const newNo = window.prompt(`Enter new unique stock number for local copy (currently ${c.stock_number}):`)
                          if (newNo && newNo.trim()) {
                            void handleResolveConflict(c.conflict_id, 'RENAME_STOCK', newNo.trim())
                          }
                        }}
                      >
                        Rename Stock No.
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="modal-actions" style={{ marginTop: 16 }}>
              <button className="secondary-button" type="button" onClick={() => setShowConflictsModal(false)}>
                Done
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}

export default App
