# Only used if minification is enabled later.
-dontwarn java.beans.**
-dontwarn javax.lang.model.**
-dontwarn javax.script.**
-dontwarn jdk.dynalink.**
-keep class org.mozilla.javascript.** { *; }
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class com.androx.app.** { kotlinx.serialization.KSerializer serializer(...); }
