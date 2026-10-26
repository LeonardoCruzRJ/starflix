import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.starflix.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.starflix.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 665  // 57.31: sobe a cada versão (o launcher da TV só troca o ícone em cache quando versionCode/recursos mudam)
        versionName = "1.0.665"
    }

    val ks = Properties().apply {
        val f = rootProject.file("keystore.properties")
        if (f.exists()) f.inputStream().use { load(it) }
    }
    signingConfigs {
        create("release") {
            if (ks.isNotEmpty()) {
                storeFile = rootProject.file(ks.getProperty("storeFile"))
                storePassword = ks.getProperty("storePassword")
                keyAlias = ks.getProperty("keyAlias")
                keyPassword = ks.getProperty("keyPassword")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.14" }  // par do Kotlin 1.9.24
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.media3:media3-exoplayer:1.3.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.3.1")
    implementation("androidx.media3:media3-ui:1.3.1")

    // 40.7: interface da TV (Compose for TV), imagens com cabeçalho Bearer (Coil) e QR code gerado no app (ZXing core)
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.tv:tv-foundation:1.0.0-alpha11")
    implementation("androidx.tv:tv-material:1.0.0")
    implementation("io.coil-kt:coil-compose:2.6.0")
    implementation("com.google.zxing:core:3.5.3")
    // 58.11: leitor de QR do celular (CameraX + ZXing core)
    implementation("androidx.camera:camera-core:1.3.4")
    implementation("androidx.camera:camera-camera2:1.3.4")
    implementation("androidx.camera:camera-lifecycle:1.3.4")
    implementation("androidx.camera:camera-view:1.3.4")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")  // 40.9: cabeçalho Bearer nas imagens (Coil)
    implementation("androidx.tvprovider:tvprovider:1.0.0")  // 52.15: linha "Reproduzir a seguir" (WatchNextProgram)
    implementation("androidx.security:security-crypto:1.1.0-alpha06")  // 40.8: token da TV criptografado
}
