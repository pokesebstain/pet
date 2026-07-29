<template>
  <el-container class="app-layout">
    <Sidebar />
    <el-container>
      <Header />
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'
</script>

<style scoped>
.app-layout { height: 100vh; }
.el-main { background: #f5f7fa; padding: 16px; overflow: auto; }
</style>
