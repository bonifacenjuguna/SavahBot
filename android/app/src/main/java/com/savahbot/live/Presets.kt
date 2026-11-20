package com.savahbot.live

import org.json.JSONArray
import org.json.JSONObject

/**
 * Saved layouts and looks ("PUBG landscape", "Chat only"): theme, opacities, text and pop-out sizes, the panel's size and place, and the tab's edge.
 * Kept as JSON in the app's own storage; every read is defensive, so a damaged value just means no presets.
 */
object Presets {
    const val MAX = 8

    class Preset(val name: String, val values: JSONObject)

    fun list(store: Store): List<Preset> {
        val out = ArrayList<Preset>()
        try {
            val arr = JSONArray(store.presetsJson.ifEmpty { "[]" })
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                out.add(Preset(o.optString("name", "Preset ${i + 1}").take(24), o))
            }
        } catch (e: Exception) {
            // unreadable: start again with none
        }
        return out
    }

    private fun write(store: Store, items: List<Preset>) {
        val arr = JSONArray()
        for (p in items) arr.put(p.values)
        store.presetsJson = arr.toString()
    }

    /** Saves the current look and layout under [name] (replacing a preset of the same name). Returns false when there are already [MAX]. */
    fun save(store: Store, name: String): Boolean {
        val clean = name.trim().ifEmpty { "Preset" }.take(24)
        val items = list(store).filter { !it.name.equals(clean, ignoreCase = true) }.toMutableList()
        if (items.size >= MAX) return false
        val o = JSONObject()
            .put("name", clean)
            .put("themeId", store.themeId).put("customHue", store.customHue).put("customLight", store.customLight)
            .put("panelOpacity", store.panelOpacity).put("tabOpacity", store.tabOpacity).put("textScale", store.textScale)
            .put("popScale", store.popScale).put("popOpacity", store.popOpacity)
            .put("panelWdp", store.panelWdp).put("panelHdp", store.panelHdp).put("panelFx", store.panelFx).put("panelFy", store.panelFy)
            .put("expanded", store.expanded).put("tabEdge", store.tabEdge).put("tabAlong", store.tabAlong)
        items.add(Preset(clean, o))
        write(store, items)
        store.presetIndex = items.size - 1
        return true
    }

    fun apply(store: Store, index: Int): String? {
        val p = list(store).getOrNull(index) ?: return null
        val o = p.values
        store.themeId = o.optInt("themeId", store.themeId)
        store.customHue = o.optInt("customHue", store.customHue)
        store.customLight = o.optInt("customLight", store.customLight)
        store.panelOpacity = o.optInt("panelOpacity", store.panelOpacity)
        store.tabOpacity = o.optInt("tabOpacity", store.tabOpacity)
        store.textScale = o.optInt("textScale", store.textScale)
        store.popScale = o.optInt("popScale", store.popScale)
        store.popOpacity = o.optInt("popOpacity", store.popOpacity)
        store.panelWdp = o.optInt("panelWdp", store.panelWdp)
        store.panelHdp = o.optInt("panelHdp", store.panelHdp)
        store.panelFx = o.optInt("panelFx", store.panelFx)
        store.panelFy = o.optInt("panelFy", store.panelFy)
        store.expanded = o.optBoolean("expanded", store.expanded)
        store.tabEdge = o.optInt("tabEdge", store.tabEdge)
        store.tabAlong = o.optInt("tabAlong", store.tabAlong)
        store.presetIndex = index
        return p.name
    }

    /** The next preset after the one used last (wraps round). Returns its name, or null when there are none. */
    fun next(store: Store): String? {
        val n = list(store).size
        if (n == 0) return null
        return apply(store, (store.presetIndex + 1).mod(n))
    }

    fun delete(store: Store, index: Int) {
        val items = list(store).toMutableList()
        if (index !in items.indices) return
        items.removeAt(index)
        write(store, items)
        store.presetIndex = -1
    }
}
