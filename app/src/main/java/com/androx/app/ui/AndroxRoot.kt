@file:OptIn(ExperimentalMaterial3Api::class)

package com.androx.app.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.res.painterResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.androx.app.AppContainer
import com.androx.app.R
import com.androx.app.model.EditorKind
import com.androx.app.ui.automations.AutomationsScreen
import com.androx.app.ui.editor.EditorScreen
import com.androx.app.ui.editor.EditorViewModel
import com.androx.app.ui.history.HistoryScreen
import com.androx.app.ui.home.HomeScreen
import com.androx.app.ui.settings.SettingsScreen

private enum class Tab(val route: String, val label: String) {
    HOME("home", "Home"),
    AUTOMATIONS("automations", "Automations"),
    HISTORY("history", "History"),
    SETTINGS("settings", "Settings"),
}

private const val EDITOR_ROUTE = "editor?id={id}&kind={kind}"

fun editorRoute(id: String?, kind: EditorKind): String =
    if (id == null) "editor?kind=${kind.name}" else "editor?id=$id&kind=${kind.name}"

@Composable
fun AndroxRoot(container: AppContainer) {
    val navController = rememberNavController()
    val mainVm: MainViewModel = viewModel(factory = viewModelFactory { initializer { MainViewModel(container) } })
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(Unit) {
        mainVm.messages.collect { snackbar.showSnackbar(it) }
    }

    val backStack by navController.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val showBar = Tab.values().any { it.route == route }

    fun openTab(tab: Tab) {
        navController.navigate(tab.route) {
            popUpTo(navController.graph.findStartDestination().id) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    fun openEditor(id: String?, kind: EditorKind) = navController.navigate(editorRoute(id, kind))

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            AnimatedVisibility(
                visible = showBar,
                enter = fadeIn(tween(160)) + expandVertically(tween(200)),
                exit = fadeOut(tween(120)) + shrinkVertically(tween(160)),
            ) {
                NavigationBar {
                    Tab.values().forEach { tab ->
                        NavigationBarItem(
                            selected = route == tab.route,
                            onClick = { openTab(tab) },
                            icon = { Icon(tabIcon(tab), contentDescription = null) },
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Tab.HOME.route,
            modifier = Modifier.padding(bottom = padding.calculateBottomPadding()),
            enterTransition = { fadeIn(tween(220)) + scaleIn(initialScale = 0.97f, animationSpec = tween(220)) },
            exitTransition = { fadeOut(tween(120)) },
            popEnterTransition = { fadeIn(tween(220)) + scaleIn(initialScale = 0.97f, animationSpec = tween(220)) },
            popExitTransition = { fadeOut(tween(120)) },
        ) {
            composable(Tab.HOME.route) {
                HomeScreen(
                    vm = mainVm,
                    onCreate = { kind -> openEditor(null, kind) },
                    onOpenHistory = { openTab(Tab.HISTORY) },
                )
            }
            composable(Tab.AUTOMATIONS.route) {
                AutomationsScreen(
                    vm = mainVm,
                    onCreate = { kind -> openEditor(null, kind) },
                    onEdit = { automation -> openEditor(automation.id, automation.editor) },
                )
            }
            composable(Tab.HISTORY.route) { HistoryScreen(vm = mainVm) }
            composable(Tab.SETTINGS.route) { SettingsScreen(vm = mainVm) }
            composable(
                route = EDITOR_ROUTE,
                arguments = listOf(
                    navArgument("id") { type = NavType.StringType; defaultValue = "" },
                    navArgument("kind") { type = NavType.StringType; defaultValue = EditorKind.BUILDER.name },
                ),
                enterTransition = { slideInVertically(tween(260)) { it / 10 } + fadeIn(tween(220)) },
                exitTransition = { fadeOut(tween(120)) },
                popEnterTransition = { fadeIn(tween(200)) },
                popExitTransition = { slideOutVertically(tween(200)) { it / 10 } + fadeOut(tween(160)) },
            ) { entry ->
                val id = entry.arguments?.getString("id").orEmpty().ifBlank { null }
                val kind = runCatching { EditorKind.valueOf(entry.arguments?.getString("kind").orEmpty()) }
                    .getOrDefault(EditorKind.BUILDER)
                val editorVm: EditorViewModel = viewModel(
                    factory = viewModelFactory { initializer { EditorViewModel(container, id, kind) } }
                )
                EditorScreen(vm = editorVm, onClose = { navController.popBackStack() })
            }
        }
    }
}

@Composable
private fun tabIcon(tab: Tab): Painter = when (tab) {
    Tab.HOME -> androidx.compose.ui.graphics.vector.rememberVectorPainter(Icons.Filled.Home)
    Tab.AUTOMATIONS -> painterResource(R.drawable.ic_bolt)
    Tab.HISTORY -> painterResource(R.drawable.ic_history)
    Tab.SETTINGS -> androidx.compose.ui.graphics.vector.rememberVectorPainter(Icons.Filled.Settings)
}
