import request from '@/utils/request'

/**
 * 分页模糊查询列表
 */
export function getEquipmentPageList(params) {
  return request({
    url: '/api/equipment/list',
    method: 'get',
    params
  })
}

/**
 * 查询某台设备某天还能开始预约的时刻
 */
export function getEquipmentStartsApi(equipmentId, params) {
  return request({
    url: `/api/equipment/${equipmentId}/starts`,
    method: 'get',
    params
  })
}

/**
 * 新增
 */
export function createEquipmentApi(data) {
  return request({
    url: '/api/equipment',
    method: 'post',
    data
  })
}

/**
 * 修改
 */
export function updateEquipmentApi(equipmentId, data) {
  return request({
    url: `/api/equipment/${equipmentId}`,
    method: 'put',
    data
  })
}

/**
 * 删除
 */
export function deleteEquipmentApi(equipmentId) {
  return request({
    url: `/api/equipment/${equipmentId}`,
    method: 'delete'
  })
}
