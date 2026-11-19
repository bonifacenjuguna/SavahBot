@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui.editor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.androx.app.engine.ScriptApiDocs
import com.androx.app.model.Action
import com.androx.app.ui.components.EmptyState
import com.androx.app.ui.theme.CodeTextStyle
import androidx.compose.ui.res.painterResource
import com.androx.app.R

private val snippets = listOf(
    "Notify" to "androx.notify(\"Title\", \"Message\");\n",
    "Counter" to "const n = Number(androx.getVar(\"count\") || 0) + 1;\nandrox.setVar(\"count\", n);\nandrox.log(\"count is \" + n);\n",
    "Battery check" to "if (androx.battery() < 20 && !androx.isCharging()) {\n  androx.notify(\"Low battery\", androx.battery() + \"% left\");\n}\n",
    "Read a variable" to "const value = androx.getVar(\"name\");\nandrox.log(value === null ? \"not set\" : value);\n",
)

private val TOKEN = Regex(
    """(//[^\n]*|/\*[\s\S]*?\*/)|("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|\b(const|let|var|function|return|if|else|for|while|do|break|continue|true|false|null|undefined|new|try|catch|finally|throw|typeof|of|in)\b|\b(androx|console)\b|\b(\d+(?:\.\d+)?)\b"""
)

private class JsHighlighter(
    private val comment: Color,
    private val string: Color,
    private val keyword: Color,
    private val builtin: Color,
    private val number: Color,
) : VisualTransformation {
    override fun filter(text: AnnotatedString): TransformedText {
        val styled = buildAnnotatedString {
            append(text.text)
            for (m in TOKEN.findAll(text.text)) {
                val color = when {
                    m.groups[1] != null -> comment
                    m.groups[2] != null -> string
                    m.groups[3] != null -> keyword
                    m.groups[4] != null -> builtin
                    else -> number
                }
                addStyle(SpanStyle(color = color), m.range.first, m.range.last + 1)
            }
        }
        return TransformedText(styled, OffsetMapping.Identity)
    }
}

@Composable
fun ScriptTab(vm: EditorViewModel) {
    val index = vm.scriptIndex
    var showApi by remember { mutableStateOf(false) }
    var snippetMenu by remember { mutableStateOf(false) }

    if (index < 0) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            EmptyState(
                icon = painterResource(R.drawable.ic_code),
                title = "No script in this automation",
                message = "Add a JavaScript action. It runs together with the other actions, in order.",
            ) {
                Button(onClick = { vm.addAction(Action.RunScript()) }) { Text("Add script") }
            }
        }
        return
    }
    val script = vm.actions[index] as Action.RunScript
    val scheme = MaterialTheme.colorScheme
    val highlighter = remember(scheme) {
        JsHighlighter(
            comment = scheme.outline,
            string = scheme.onSurface.copy(alpha = 0.75f),
            keyword = scheme.primary,
            builtin = scheme.tertiary,
            number = scheme.secondary,
        )
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Card(colors = CardDefaults.cardColors(containerColor = scheme.surfaceContainerLow)) {
            Text(
                "Runs in an embedded JavaScript interpreter (Rhino) with only the androx API. " +
                    "No network, files or Android classes are reachable. Scripts stop after 5 seconds.",
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
                modifier = Modifier.padding(12.dp),
            )
        }
        if (vm.actions.size > 1) {
            Text(
                "This automation has ${vm.actions.size - 1} other action${if (vm.actions.size == 2) "" else "s"}. " +
                    "They stay as they are and run in order; edit them in the Builder.",
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box {
                AssistChip(
                    onClick = { snippetMenu = true },
                    label = { Text("Insert snippet") },
                    leadingIcon = { Icon(Icons.Filled.Add, contentDescription = null) },
                )
                DropdownMenu(expanded = snippetMenu, onDismissRequest = { snippetMenu = false }) {
                    snippets.forEach { (title, code) ->
                        DropdownMenuItem(
                            text = { Text(title) },
                            onClick = {
                                snippetMenu = false
                                val base = if (script.source.isEmpty() || script.source.endsWith("\n")) script.source else script.source + "\n"
                                vm.setScript(base + code)
                            },
                        )
                    }
                }
            }
            AssistChip(onClick = { showApi = true }, label = { Text("API reference") })
        }
        OutlinedTextField(
            value = script.source,
            onValueChange = { vm.setScript(it) },
            label = { Text("Script") },
            textStyle = CodeTextStyle,
            visualTransformation = highlighter,
            modifier = Modifier.fillMaxWidth().heightIn(min = 320.dp),
        )
    }

    if (showApi) {
        ModalBottomSheet(onDismissRequest = { showApi = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            Column(
                Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Androx scripting API", style = MaterialTheme.typography.titleLarge)
                ScriptApiDocs.entries.forEach { entry ->
                    Column {
                        Text(entry.signature, style = CodeTextStyle.copy(fontFamily = FontFamily.Monospace), color = scheme.primary)
                        Text(entry.description, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
                    }
                }
                Text(
                    "Variables are shared by every automation and are always text. A script that throws, or a notification Android blocks, " +
                        "is recorded as a failed run in History.",
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                )
            }
        }
    }
}
