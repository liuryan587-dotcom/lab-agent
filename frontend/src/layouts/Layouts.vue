<template>
  <div class="common-layout">
    <el-container style="min-height: 100vh">
      <el-header
        style="
          display: flex;
          border-bottom: 1px solid #ccc;
          align-items: center;
          background-color: #fff;
        "
      >
        <div
          style="flex: 1; display: flex; align-items: center; font-size: 24px; font-weight: bold"
        >
          <img src="@/assets/imgs/logo.png" style="width: 40px; height: 40px" />
          <div style="margin-left: 5px">实验室预约系统</div>
        </div>
        <el-dropdown trigger="click" @command="handleCommand">
          <div class="user-area">
            <img src="@/assets/imgs/logo.png" class="user-avatar" />
            <span>管理员</span>
            <el-icon><ArrowDown /></el-icon>
          </div>

          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout"> 退出登录 </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-container>
        <el-aside width="220px">
          <el-menu
            router
            style="height: 100%; border-right: 1px solid #ccc"
            default-active="/manager/home"
          >
            <el-menu-item index="/manager/home">
              <el-icon><icon-menu /></el-icon>
              <span>系统首页</span>
            </el-menu-item>
            <el-menu-item index="/manager/lab">
              <el-icon><House /></el-icon>
              <span>实验室管理</span>
            </el-menu-item>
            <el-menu-item index="/manager/equipment">
              <el-icon><Setting /></el-icon>
              <span>设备管理</span>
            </el-menu-item>
            <el-menu-item index="/manager/user">
              <el-icon><User /></el-icon>
              <span>用户管理</span>
            </el-menu-item>
          </el-menu>
        </el-aside>
        <el-main style="background-color: lightgray">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import router from '@/router'
import { logout } from '@/utils/auth'
import { Menu as IconMenu, Location, Setting, House } from '@element-plus/icons-vue'
const handleCommand = (command) => {
  if (command === 'logout') {
    logout()
    router.replace('/login')
  }
}
</script>

<style scoped>
.user-area {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.user-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
}
</style>
