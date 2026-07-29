import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http';
export const customersApi = {
    list: (page, pageSize, search) => listPage('/customers', { page, page_size: pageSize, search }),
    get: (id) => getOne(`/customers/${id}`),
    create: (payload) => createOne('/customers', payload),
    update: (id, payload) => updateOne(`/customers/${id}`, payload),
    remove: (id) => deleteOne(`/customers/${id}`)
};
//# sourceMappingURL=customers.js.map