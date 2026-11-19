package com.androx.app.data

import com.androx.app.engine.VariableStore
import com.androx.app.model.Automation
import com.androx.app.model.ExecutionRecord
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/** In-memory state backed by a JSON file. Loaded once in the background; every update is persisted. */
class PersistentState<T>(
    private val file: JsonFile<T>,
    scope: CoroutineScope,
    initial: T,
) {
    private val _state = MutableStateFlow(initial)
    val state: StateFlow<T> = _state.asStateFlow()

    private val _loaded = MutableStateFlow(false)
    val loaded: StateFlow<Boolean> = _loaded.asStateFlow()

    private val ready = CompletableDeferred<Unit>()
    private val writeMutex = Mutex()

    init {
        scope.launch(Dispatchers.IO) {
            _state.value = file.read()
            _loaded.value = true
            ready.complete(Unit)
        }
    }

    suspend fun awaitLoaded() = ready.await()

    suspend fun update(transform: (T) -> T): T {
        ready.await()
        return writeMutex.withLock {
            val next = transform(_state.value)
            _state.value = next
            withContext(Dispatchers.IO) { file.write(next) }
            next
        }
    }
}

class AutomationRepository(
    dir: File,
    scope: CoroutineScope,
    private val onChanged: (List<Automation>) -> Unit,
) {
    private val store = PersistentState(
        JsonFile(File(dir, "automations.json"), ListSerializer(Automation.serializer())) { emptyList() },
        scope,
        emptyList(),
    )
    val state: StateFlow<List<Automation>> get() = store.state
    val loaded: StateFlow<Boolean> get() = store.loaded

    suspend fun awaitLoaded() = store.awaitLoaded()

    fun get(id: String): Automation? = store.state.value.firstOrNull { it.id == id }

    suspend fun upsert(automation: Automation) = change { list ->
        if (list.any { it.id == automation.id }) list.map { if (it.id == automation.id) automation else it }
        else list + automation
    }

    suspend fun addAll(items: List<Automation>) = change { it + items }

    suspend fun delete(id: String) = change { list -> list.filterNot { it.id == id } }

    suspend fun setEnabled(id: String, enabled: Boolean) = change { list ->
        list.map { if (it.id == id) it.copy(enabled = enabled, updatedAt = System.currentTimeMillis()) else it }
    }

    private suspend fun change(transform: (List<Automation>) -> List<Automation>) {
        val next = store.update(transform)
        onChanged(next)
    }
}

class HistoryRepository(dir: File, scope: CoroutineScope) {
    private val store = PersistentState(
        JsonFile(File(dir, "history.json"), ListSerializer(ExecutionRecord.serializer())) { emptyList() },
        scope,
        emptyList(),
    )
    val state: StateFlow<List<ExecutionRecord>> get() = store.state
    val loaded: StateFlow<Boolean> get() = store.loaded

    suspend fun awaitLoaded() = store.awaitLoaded()

    /** Newest first, trimmed to [limit]. */
    suspend fun add(record: ExecutionRecord, limit: Int) {
        store.update { (listOf(record) + it).take(limit.coerceAtLeast(1)) }
    }

    suspend fun trim(limit: Int) {
        store.update { it.take(limit.coerceAtLeast(1)) }
    }

    suspend fun clear() {
        store.update { emptyList() }
    }
}

/** Variables are read and written synchronously (scripts need that) and persisted in the background. */
class VariableRepository(dir: File, private val scope: CoroutineScope) : VariableStore {
    private val file = JsonFile(
        File(dir, "variables.json"),
        MapSerializer(String.serializer(), String.serializer()),
    ) { emptyMap() }
    private val map = ConcurrentHashMap<String, String>()
    private val _snapshot = MutableStateFlow<Map<String, String>>(emptyMap())
    val snapshot: StateFlow<Map<String, String>> = _snapshot.asStateFlow()
    private val ready = CompletableDeferred<Unit>()
    private val writeMutex = Mutex()

    init {
        scope.launch(Dispatchers.IO) {
            file.read().forEach { (k, v) -> map.putIfAbsent(k, v) }
            publish()
            ready.complete(Unit)
        }
    }

    suspend fun awaitLoaded() = ready.await()

    override fun get(name: String): String? = map[name]

    override fun set(name: String, value: String) {
        map[name] = value
        changed()
    }

    override fun remove(name: String) {
        map.remove(name)
        changed()
    }

    fun clear() {
        map.clear()
        changed()
    }

    private fun publish() {
        _snapshot.value = map.toSortedMap()
    }

    private fun changed() {
        publish()
        scope.launch(Dispatchers.IO) {
            writeMutex.withLock { file.write(map.toMap()) }
        }
    }
}
