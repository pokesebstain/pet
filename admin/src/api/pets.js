import { listPage, getOne, createOne, updateOne, deleteOne } from '@/utils/http';
export const petsApi = {
    list: (page, pageSize, search) => listPage('/pets', { page, page_size: pageSize, search }),
    get: (id) => getOne(`/pets/${id}`),
    create: (payload) => createOne('/pets', payload),
    update: (id, payload) => updateOne(`/pets/${id}`, payload),
    remove: (id) => deleteOne(`/pets/${id}`)
};
//# sourceMappingURL=pets.js.map