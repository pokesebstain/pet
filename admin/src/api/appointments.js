import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http';
export const appointmentsApi = {
    list: (page, pageSize, filters = {}) => listPage('/appointments', { page, page_size: pageSize, ...filters }),
    get: (id) => getOne(`/appointments/${id}`),
    create: (payload) => createOne('/appointments', payload),
    update: (id, payload) => updateOne(`/appointments/${id}`, payload),
    cancel: (id) => deleteOne(`/appointments/${id}`)
};
//# sourceMappingURL=appointments.js.map