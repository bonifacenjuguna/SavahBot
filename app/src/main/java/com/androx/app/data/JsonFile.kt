package com.androx.app.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import java.io.File

/**
 * A small JSON document stored in one file. Writes go to a temp file first so a crash mid-write
 * can't corrupt the saved data. A file that can't be parsed is kept as `<name>.corrupt` instead of being overwritten.
 */
class JsonFile<T>(
    private val file: File,
    private val serializer: KSerializer<T>,
    private val fallback: () -> T,
) {
    companion object {
        val json = Json {
            ignoreUnknownKeys = true
            encodeDefaults = true
            classDiscriminator = "type"
        }
    }

    fun read(): T {
        if (!file.exists()) return fallback()
        return try {
            json.decodeFromString(serializer, file.readText())
        } catch (e: Exception) {
            runCatching { file.copyTo(File(file.parentFile, file.name + ".corrupt"), overwrite = true) }
            fallback()
        }
    }

    fun write(value: T) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.encodeToString(serializer, value))
        if (!tmp.renameTo(file)) {
            file.delete()
            if (!tmp.renameTo(file)) throw java.io.IOException("Could not save ${file.name}")
        }
    }
}
