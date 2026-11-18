package com.savahbot.live

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Everything the app remembers: where SavahBot is, this phone's device key, and a few overlay choices.
 * The device key is encrypted with an AES key that lives in the Android Keystore and cannot be taken out of the phone.
 * It is never a SavahBot sign-in: it only opens the overlay feed, and SavahBot can cancel it at any time.
 */
class Store(context: Context) {
    private val prefs: SharedPreferences = context.applicationContext.getSharedPreferences("savahlive", Context.MODE_PRIVATE)

    val server: String get() = prefs.getString("server", "") ?: ""
    val deviceName: String get() = prefs.getString("name", "") ?: ""
    val expires: Long get() = prefs.getLong("expires", 0L)          // epoch milliseconds, 0 = until removed

    /** What to tell the person next time the app opens (for example that SavahBot unpaired this phone). */
    var notice: String
        get() = prefs.getString("notice", "") ?: ""
        set(v) { prefs.edit().putString("notice", v).apply() }

    /** 0 solid, 1 glass, 2 ghost (text only). */
    var opacity: Int
        get() = prefs.getInt("opacity", 1)
        set(v) { prefs.edit().putInt("opacity", v).apply() }

    val posX: Int get() = prefs.getInt("posX", -1)
    val posY: Int get() = prefs.getInt("posY", -1)
    val dock: Int get() = prefs.getInt("dock", 0)

    fun savePosition(x: Int, y: Int, dock: Int) {
        prefs.edit().putInt("posX", x).putInt("posY", y).putInt("dock", dock).apply()
    }

    val isPaired: Boolean get() = server.isNotEmpty() && key() != null

    /** The device key, or null when there is none (or the Keystore could not open it, in which case the phone simply pairs again). */
    fun key(): String? {
        val sealed = prefs.getString("key", null) ?: return null
        return Vault.unseal(sealed)
    }

    /** Written in one go, and synchronously, so a pairing is never half saved. */
    fun savePairing(server: String, key: String, name: String, expires: Long) {
        prefs.edit()
            .putString("server", server)
            .putString("key", Vault.seal(key))
            .putString("name", name)
            .putLong("expires", expires)
            .putString("notice", "")
            .commit()
    }

    /** A renewed key from SavahBot. Synchronous on purpose: losing it would mean pairing again. */
    fun saveKey(key: String) {
        prefs.edit().putString("key", Vault.seal(key)).commit()
    }

    fun clearPairing(notice: String) {
        prefs.edit().remove("server").remove("key").remove("name").remove("expires").putString("notice", notice).commit()
    }

    private object Vault {
        private const val ALIAS = "savahlive_device_key"

        private fun secretKey(): SecretKey {
            val ks = KeyStore.getInstance("AndroidKeyStore")
            ks.load(null)
            val existing = ks.getKey(ALIAS, null)
            if (existing is SecretKey) return existing
            val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            gen.init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
            return gen.generateKey()
        }

        /** "v1:" + base64(iv + ciphertext). If the Keystore is unusable on some phone, the key is kept in the app's private storage as it is ("p:"). */
        fun seal(plain: String): String {
            return try {
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.ENCRYPT_MODE, secretKey())
                val ct = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
                "v1:" + Base64.encodeToString(cipher.iv + ct, Base64.NO_WRAP)
            } catch (e: Exception) {
                "p:$plain"
            }
        }

        fun unseal(sealed: String): String? {
            if (sealed.startsWith("p:")) return sealed.substring(2)
            if (!sealed.startsWith("v1:")) return null
            return try {
                val raw = Base64.decode(sealed.substring(3), Base64.NO_WRAP)
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, raw.copyOfRange(0, 12)))
                String(cipher.doFinal(raw.copyOfRange(12, raw.size)), Charsets.UTF_8)
            } catch (e: Exception) {
                null
            }
        }
    }
}
