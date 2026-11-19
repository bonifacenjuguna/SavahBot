package com.androx.app.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Androx brand palette: black, white, charcoal, greys and silver. Red is kept only for errors.
private val Black = Color(0xFF000000)
private val White = Color(0xFFFFFFFF)
private val Charcoal = Color(0xFF1C1C1E)
private val DarkGrey = Color(0xFF3A3A3C)
private val Silver = Color(0xFFC0C0C0)
private val LightGrey = Color(0xFFE4E4E6)

private val AndroxLight: ColorScheme = lightColorScheme(
    primary = Charcoal,
    onPrimary = White,
    primaryContainer = LightGrey,
    onPrimaryContainer = Charcoal,
    secondary = Color(0xFF5C5C60),
    onSecondary = White,
    secondaryContainer = Color(0xFFE9E9EB),
    onSecondaryContainer = Charcoal,
    tertiary = Color(0xFF6E6E73),
    onTertiary = White,
    tertiaryContainer = Color(0xFFDADADD),
    onTertiaryContainer = Charcoal,
    background = Color(0xFFFBFBFB),
    onBackground = Charcoal,
    surface = Color(0xFFFBFBFB),
    onSurface = Charcoal,
    surfaceVariant = Color(0xFFE4E4E6),
    onSurfaceVariant = Color(0xFF48484A),
    surfaceTint = Charcoal,
    outline = Color(0xFF8E8E93),
    outlineVariant = Color(0xFFD1D1D6),
    surfaceContainerLowest = White,
    surfaceContainerLow = Color(0xFFF5F5F6),
    surfaceContainer = Color(0xFFEFEFF0),
    surfaceContainerHigh = Color(0xFFE9E9EB),
    surfaceContainerHighest = Color(0xFFE3E3E5),
    inverseSurface = Charcoal,
    inverseOnSurface = Color(0xFFF2F2F7),
    inversePrimary = Silver,
)

private val AndroxDark: ColorScheme = darkColorScheme(
    primary = Color(0xFFE6E6E8),
    onPrimary = Charcoal,
    primaryContainer = DarkGrey,
    onPrimaryContainer = Color(0xFFF2F2F7),
    secondary = Silver,
    onSecondary = Charcoal,
    secondaryContainer = Color(0xFF2C2C2E),
    onSecondaryContainer = Color(0xFFE6E6E8),
    tertiary = Color(0xFFA1A1A6),
    onTertiary = Charcoal,
    tertiaryContainer = Color(0xFF38383A),
    onTertiaryContainer = Color(0xFFE6E6E8),
    background = Color(0xFF0E0E0E),
    onBackground = Color(0xFFE6E6E8),
    surface = Color(0xFF0E0E0E),
    onSurface = Color(0xFFE6E6E8),
    surfaceVariant = Color(0xFF2C2C2E),
    onSurfaceVariant = Color(0xFFAEAEB2),
    surfaceTint = Color(0xFFE6E6E8),
    outline = Color(0xFF8E8E93),
    outlineVariant = Color(0xFF3A3A3C),
    surfaceContainerLowest = Black,
    surfaceContainerLow = Color(0xFF151516),
    surfaceContainer = Color(0xFF1A1A1C),
    surfaceContainerHigh = Color(0xFF232325),
    surfaceContainerHighest = Color(0xFF2C2C2E),
    inverseSurface = Color(0xFFE6E6E8),
    inverseOnSurface = Charcoal,
    inversePrimary = Charcoal,
)

private val AndroxTypography = Typography().let { base ->
    base.copy(
        headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.SemiBold, letterSpacing = (-0.25).sp),
        titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
    )
}

/** Monospace style for the script editor. */
val CodeTextStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.sp, lineHeight = 19.sp)

@Composable
fun AndroxTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    pureBlack: Boolean = false,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    var scheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> AndroxDark
        else -> AndroxLight
    }
    if (darkTheme && pureBlack) {
        scheme = scheme.copy(
            background = Black,
            surface = Black,
            surfaceContainerLowest = Black,
            surfaceContainerLow = Color(0xFF0A0A0A),
            surfaceContainer = Color(0xFF111112),
            surfaceContainerHigh = Color(0xFF1A1A1C),
            surfaceContainerHighest = Color(0xFF232325),
        )
    }
    MaterialTheme(colorScheme = scheme, typography = AndroxTypography, content = content)
}
